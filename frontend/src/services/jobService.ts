import api from './api';
import type { CompanyProfile } from '@/types/company';
import type { FitAnalysis } from '@/types/fit';
import type { Job, JobSearchRequest, JobListResponse, JobAnalysisResponse } from '@/types/job';
import type { ResumeRecommendation } from '@/types/resumeRecommendation';

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

/**
 * Assess one CV against this job. Job-first: the job is the context and the CV is the
 * variable, which is the opposite of picking a CV and then hunting for a job.
 *
 * A stored analysis for this exact (job, CV) pair is returned unless `refresh` is set.
 */
export async function analyseFit(
  jobId: string,
  resumeId: string,
  refresh = false,
): Promise<FitAnalysis> {
  const { data } = await api.post<FitAnalysis>(`/jobs/${jobId}/fit`, {
    resume_id: resumeId,
    refresh,
  });
  return data;
}

/** A previously stored assessment, without recomputing. `null` when none exists. */
export async function getStoredFit(
  jobId: string,
  resumeId?: string,
): Promise<FitAnalysis | null> {
  const { data } = await api.get<FitAnalysis | null>(`/jobs/${jobId}/fit`, {
    params: resumeId ? { resume_id: resumeId } : undefined,
  });
  return data;
}

/** What is actually known about this job's employer. */
export async function getCompanyProfile(jobId: string): Promise<CompanyProfile> {
  const { data } = await api.get<CompanyProfile>(`/jobs/${jobId}/company`);
  return data;
}

/** Every résumé ranked against this job, with the winner called out and explained. Backs
 *  the floating ATS widget — visible regardless of which page the operator is on. */
export async function getResumeRecommendation(jobId: string): Promise<ResumeRecommendation> {
  const { data } = await api.get<ResumeRecommendation>(`/jobs/${jobId}/resume-recommendation`);
  return data;
}

/** Fetch the full posting for a job and persist its requirements. */
export async function enrichJob(jobId: string, force = false): Promise<Job> {
  const { data } = await api.post<Job>(`/jobs/${jobId}/enrich`, null, { params: { force } });
  return data;
}
