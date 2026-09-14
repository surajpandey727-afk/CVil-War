import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as jobService from '@/services/jobService';
import type { JobSearchRequest } from '@/types/job';

const JOBS_KEY = ['jobs'] as const;

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
  filters: { location?: string; query?: string } = {},
) {
  const location = filters.location?.trim() || undefined;
  const query = filters.query?.trim() || undefined;
  return useQuery({
    queryKey: [...JOBS_KEY, 'list', page, pageSize, status, location, query],
    queryFn: () => jobService.listJobs(page, pageSize, status, { location, query }),
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
