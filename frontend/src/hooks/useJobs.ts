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
