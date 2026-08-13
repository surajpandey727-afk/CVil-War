import api from './api';
import type { Job, JobSearchRequest, JobListResponse, JobAnalysisResponse } from '@/types/job';

/** Search for jobs across multiple platforms. */
export async function searchJobs(request: JobSearchRequest): Promise<JobListResponse> {
  const { data } = await api.post<JobListResponse>('/jobs/search', request);
  return data;
}

/** List stored jobs with pagination and optional status filter. */
export async function listJobs(
  page = 1,
  pageSize = 20,
  status?: string,
  filters: { location?: string; query?: string } = {},
): Promise<JobListResponse> {
  const params: Record<string, string | number> = { page, page_size: pageSize };
  if (status) params['status'] = status;
  // Location and title go to the server. Filtering them in the browser meant `total`
  // counted every stored job and page 2 of a London search was not London — the filter
  // existed only in the rendered list.
  if (filters.location?.trim()) params['location'] = filters.location.trim();
  if (filters.query?.trim()) params['q'] = filters.query.trim();
  const { data } = await api.get<JobListResponse>('/jobs/', { params });
  return data;
}

/** Get a single job by ID. */
export async function getJob(jobId: string): Promise<Job> {
  const { data } = await api.get<Job>(`/jobs/${jobId}`);
  return data;
}

/** Analyze how well the candidate matches a job listing. */
export async function analyzeJob(jobId: string): Promise<JobAnalysisResponse> {
  const { data } = await api.post<JobAnalysisResponse>(`/jobs/${jobId}/analyze`);
  return data;
}
