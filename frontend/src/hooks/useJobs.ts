import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as jobService from '@/services/jobService';
import type { Job, JobSearchRequest, WorkplaceType } from '@/types/job';

const JOBS_KEY = ['jobs'] as const;

/** Jobs per scoring request — small enough to finish well inside one serverless invocation. */
const SCORE_BATCH = 25;

/**
 * Fetch paginated job listings.
 *
 * `filters` is part of the query key, so changing the location refetches rather than
 * re-filtering a stale page — the server decides what matches.
 */
export function useJobs(
  page = 1,
  pageSize = 20,
  status?: string,
  filters: { location?: string; query?: string; workplace?: WorkplaceType } = {},
) {
  const location = filters.location?.trim() || undefined;
  const query = filters.query?.trim() || undefined;
  const workplace = filters.workplace;
  return useQuery({
    queryKey: [...JOBS_KEY, 'list', page, pageSize, status, location, query, workplace],
    queryFn: () => jobService.listJobs(page, pageSize, status, { location, query, workplace }),
    // Keep the current page on screen while the next one loads, instead of flashing empty.
    placeholderData: (previous) => previous,
  });
}

/** Shown / hidden-outside-UK / quarantined counts behind the jobs list. */
export function useLocationSummary() {
  return useQuery({
    queryKey: [...JOBS_KEY, 'location-summary'],
    queryFn: () => jobService.getLocationSummary(),
    staleTime: 60_000,
  });
}

/** Fetch a single job by ID. */
export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: [...JOBS_KEY, 'detail', jobId],
    queryFn: () => jobService.getJob(jobId!),
    enabled: !!jobId,
  });
}

/** Search for jobs across platforms. */
export function useSearchJobs() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: JobSearchRequest) => jobService.searchJobs(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: JOBS_KEY });
    },
  });
}

/** Analyze a job's match score. */
export function useAnalyzeJob() {
  return useMutation({
    mutationFn: (jobId: string) => jobService.analyzeJob(jobId),
  });
}

/** The stored fit assessment for a job, if one exists. */
export function useStoredFit(jobId: string | undefined, resumeId?: string) {
  return useQuery({
    queryKey: [...JOBS_KEY, 'fit', jobId, resumeId],
    queryFn: () => jobService.getStoredFit(jobId!, resumeId),
    enabled: !!jobId,
  });
}

/**
 * Run a fit analysis. A mutation because it is an explicit, potentially expensive action —
 * analysing on render would fire a model call every time a drawer opened.
 */
export function useAnalyseFit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, resumeId, refresh }: { jobId: string; resumeId: string; refresh?: boolean }) =>
      jobService.analyseFit(jobId, resumeId, refresh ?? false),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: [...JOBS_KEY, 'fit', variables.jobId] });
    },
  });
}

/** Every résumé ranked against this job. Powers both the floating ATS widget and the
 *  résumés page's "how does this score" question — one source instead of two that could
 *  disagree. A short `staleTime` keeps repeated widget mounts from refetching needlessly
 *  while still picking up a newly uploaded résumé within a few seconds. */
export function useResumeRecommendation(jobId: string | undefined) {
  return useQuery({
    queryKey: [...JOBS_KEY, 'resume-recommendation', jobId],
    queryFn: () => jobService.getResumeRecommendation(jobId!),
    enabled: !!jobId,
    staleTime: 30_000,
  });
}

/** What is known about a job's employer. */
export function useCompanyProfile(jobId: string | undefined) {
  return useQuery({
    queryKey: [...JOBS_KEY, 'company', jobId],
    queryFn: () => jobService.getCompanyProfile(jobId!),
    enabled: !!jobId,
  });
}

/**
 * Fetch the full posting for a job.
 *
 * Invalidates the job list as well as the fit analysis: enrichment is what gives the fit
 * analyser a description to read, so a fit computed before it ran was computed against
 * nothing and must not be left on screen looking authoritative.
 */
export function useEnrichJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, force }: { jobId: string; force?: boolean }) =>
      jobService.enrichJob(jobId, force),
    onSuccess: (_job, { jobId }) => {
      void qc.invalidateQueries({ queryKey: ['jobs'] });
      void qc.invalidateQueries({ queryKey: ['fit', jobId] });
    },
  });
}

/** Save, hide, or otherwise change a job's lifecycle status. There was previously no way
 *  to do this at all — a job only ever moved to "applied" as a side effect of creating an
 *  application. */
export function useUpdateJobStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, status }: { jobId: string; status: string }) =>
      jobService.updateJobStatus(jobId, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: JOBS_KEY });
    },
  });
}

/**
 * Fill in the match score of every listed job that does not have one yet.
 *
 * `match_score` was never written when jobs were stored, so every row showed "—". This asks the
 * server to score the unscored ones (one batch request, best-matching résumé for each) and then
 * refreshes the list. Each id is attempted once per session: a job with no description comes back
 * unscorable and is not asked about again on every render.
 */
export function useAutoScoreJobs(items: Job[] | undefined) {
  const queryClient = useQueryClient();
  const attempted = useRef<Set<string>>(new Set());
  const mounted = useRef(true);
  const [scoring, setScoring] = useState(false);
  const [unscorable, setUnscorable] = useState(0);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  // How many score batches are in flight. A boolean was cleared by whichever batch finished
  // first, so "Scoring matches..." vanished while another batch was still running — and stuck
  // on screen when a later list refetch started one more.
  const inFlight = useRef(0);

  useEffect(() => {
    const todo = (items ?? []).filter((j) => j.match_score == null && !attempted.current.has(j.id)).slice(0, 100);
    if (todo.length === 0) return;
    todo.forEach((j) => attempted.current.add(j.id));
    // Small batches, one after another: each is a fast request well inside the serverless
    // time limit, and scores appear as each batch lands instead of all-or-nothing at the end.
    const batches: string[][] = [];
    for (let i = 0; i < todo.length; i += SCORE_BATCH) batches.push(todo.slice(i, i + SCORE_BATCH).map((j) => j.id));
    inFlight.current += 1;
    setScoring(true);
    void (async () => {
      for (const ids of batches) {
        try {
          const r = await jobService.scoreJobs(ids);
          if (mounted.current) setUnscorable((n) => n + r.skipped);
          // Refresh even if the list changed meanwhile: the scores are saved server-side.
          if (r.scored > 0) void queryClient.invalidateQueries({ queryKey: [...JOBS_KEY, 'list'] });
        } catch {
          // Scoring is an enhancement; the list works without it. Stop this run rather than
          // hammering a failing endpoint with the remaining batches.
          break;
        }
      }
      inFlight.current -= 1;
      if (mounted.current && inFlight.current === 0) setScoring(false);
    })();
  }, [items, queryClient]);

  return { scoring, unscorable };
}
