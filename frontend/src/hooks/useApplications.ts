import { useCallback, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as appService from '@/services/applicationService';
import { apiErrorMessage } from '@/lib/apiError';
import type { ApplicationScoreItem, TailorRowState } from '@/types/ats';
import type {
  ApplicationBatchCreate,
  ApplicationCreate,
  ApplicationStatusUpdate,
} from '@/types/application';

const APPS_KEY = ['applications'] as const;

/** Fetch paginated application listings. */
export function useApplications(page = 1, pageSize = 20, status?: string) {
  return useQuery({
    queryKey: [...APPS_KEY, 'list', page, pageSize, status],
    queryFn: () => appService.listApplications(page, pageSize, status),
  });
}

/** Fetch a single application by ID. */
export function useApplication(appId: string | undefined) {
  return useQuery({
    queryKey: [...APPS_KEY, 'detail', appId],
    queryFn: () => appService.getApplication(appId!),
    enabled: !!appId,
  });
}

/** Create a single application. */
export function useCreateApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ApplicationCreate) => appService.createApplication(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPS_KEY });
    },
  });
}

/** Create a whole run's worth of applications in one request. Used by the Jobs selection bar. */
export function useCreateApplicationBatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ApplicationBatchCreate) => appService.createApplicationBatch(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPS_KEY });
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

/** Approve a pending application. */
export function useApproveApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (appId: string) => appService.approveApplication(appId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPS_KEY });
    },
  });
}

/** Resolve a pending CAPTCHA/2FA intervention for an application. */
export function useResolveIntervention() {
  return useMutation({
    mutationFn: ({ appId, response }: { appId: string; response: string }) =>
      appService.resolveIntervention(appId, response),
  });
}

/** Re-queue (headed) an application paused for a CAPTCHA/verification wall. */
export function useResolveBlocker() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (appId: string) => appService.resolveBlocker(appId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPS_KEY });
    },
  });
}

/** Approve a set of staged applications together (batch flow). */
export function useBulkApprove() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => appService.bulkApprove(ids),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPS_KEY });
    },
  });
}

/** Update an application's status. */
export function useUpdateApplicationStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, update }: { appId: string; update: ApplicationStatusUpdate }) =>
      appService.updateApplicationStatus(appId, update),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPS_KEY });
    },
  });
}

/** Fetch the evidence bundle for one application. */
export function useApplicationEvidence(appId: string | undefined) {
  return useQuery({
    queryKey: [...APPS_KEY, 'evidence', appId],
    queryFn: () => appService.getApplicationEvidence(appId!),
    enabled: !!appId,
  });
}

/** Generate a cover letter for an application. Invalidates the app + its evidence bundle. */
export function useGenerateCoverLetter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (appId: string) => appService.generateCoverLetter(appId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: APPS_KEY });
    },
  });
}

/** Whether the agent can apply to a job right now — re-fetches when the picked résumé changes. */
export function useApplyReadiness(jobId: string | undefined, resumeId?: string) {
  return useQuery({
    queryKey: [...APPS_KEY, 'readiness', jobId, resumeId],
    queryFn: () => appService.getApplyReadiness(jobId!, resumeId),
    enabled: !!jobId,
  });
}

/**
 * ATS match for a set of applications, in one request.
 *
 * Rows with a résumé attached come back scored with it; the rest are scored with the best base
 * résumé for their job (the item says which). Rows that cannot be scored carry the reason, so the
 * list can say "no job description" instead of leaving a blank.
 */
export function useApplicationScores(applicationIds: string[], enabled = true) {
  const key = [...applicationIds].sort().join(',');
  const query = useQuery({
    queryKey: [...APPS_KEY, 'scores', key],
    queryFn: () => appService.scoreApplications(applicationIds),
    enabled: enabled && applicationIds.length > 0,
    staleTime: 5 * 60_000,
  });
  const byId = new Map<string, ApplicationScoreItem>((query.data?.items ?? []).map((i) => [i.application_id, i]));
  return { ...query, byId };
}

/** How many tailoring requests run at once. The server serialises per (résumé, job), and a model gateway has limits. */
const TAILOR_CONCURRENCY = 3;

/**
 * Tailor a résumé for each of several applications, tracking every row.
 *
 * Each row calls the same endpoint as the job drawer's "Get Tailored Resume", attaches the result
 * to that application and returns the generated file's own ATS score. Rows run a few at a time,
 * one failure never stops the rest, and a second `start` while one is running is ignored (a
 * double click must not spend the model twice).
 */
export function useBulkTailor() {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Record<string, TailorRowState>>({});
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);
  const cancelRef = useRef(false);

  const start = useCallback(
    async (ids: string[], opts: { baseResumeId?: string; regenerate?: boolean } = {}) => {
      if (runningRef.current || ids.length === 0) return;
      runningRef.current = true;
      cancelRef.current = false;
      setRunning(true);
      setRows(Object.fromEntries(ids.map((id) => [id, { phase: 'queued' } as TailorRowState])));
      const queue = [...ids];
      const set = (id: string, state: TailorRowState) => setRows((prev) => ({ ...prev, [id]: state }));

      const worker = async () => {
        while (queue.length && !cancelRef.current) {
          const id = queue.shift()!;
          set(id, { phase: 'running' });
          try {
            const r = await appService.tailorApplication(id, {
              base_resume_id: opts.baseResumeId || null,
              regenerate: opts.regenerate ?? false,
            });
            set(id, {
              phase: 'done', before: r.ats_before, after: r.ats_after, status: r.status,
              note: r.target_note, resumeName: r.resume.name,
            });
          } catch (err) {
            set(id, { phase: 'failed', message: apiErrorMessage(err, 'Could not tailor a résumé for this role') });
          }
        }
      };
      try {
        await Promise.all(Array.from({ length: Math.min(TAILOR_CONCURRENCY, ids.length) }, worker));
      } finally {
        // Anything still queued after a cancel is simply not run: say so rather than leave it spinning.
        setRows((prev) => Object.fromEntries(Object.entries(prev).map(([id, s]) => [id, s.phase === 'queued' ? { phase: 'failed', message: 'Cancelled before it started' } as TailorRowState : s])));
        runningRef.current = false;
        setRunning(false);
        void queryClient.invalidateQueries({ queryKey: APPS_KEY });
        void queryClient.invalidateQueries({ queryKey: ['resumes'] });
      }
    },
    [queryClient],
  );

  const cancel = useCallback(() => { cancelRef.current = true; }, []);
  const clear = useCallback(() => setRows({}), []);
  const values = Object.values(rows);
  return {
    rows,
    running,
    start,
    cancel,
    clear,
    total: values.length,
    finished: values.filter((r) => r.phase === 'done' || r.phase === 'failed').length,
    failed: values.filter((r) => r.phase === 'failed').length,
  };
}
