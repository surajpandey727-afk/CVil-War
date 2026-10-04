import api from './api';
import type {
  ApplicationScoreResponse,
  ApplicationTailorRequest,
  ApplicationTailorResponse,
} from '@/types/ats';
import type { ApplicationEvidence } from '@/types/evidence';
import type {
  Application,
  ApplicationCreate,
  ApplicationBatchCreate,
  ApplicationStatusUpdate,
  ApplicationListResponse,
  ApplyReadiness,
  CoverLetterResponse,
} from '@/types/application';

/** Create a single job application. */
export async function createApplication(
  data: ApplicationCreate,
): Promise<Application> {
  const { data: result } = await api.post<Application>('/applications/', data);
  return result;
}

/**
 * Create several applications in one request.
 *
 * Use this rather than looping `createApplication`: the endpoint dispatches each application
 * inside a single transaction and a single rate-limit slot, so a 20-role run is one round trip
 * instead of twenty — and a partial failure does not leave half a run queued.
 */
export async function createApplicationBatch(
  data: ApplicationBatchCreate,
): Promise<Application[]> {
  const { data: result } = await api.post<Application[]>('/applications/batch', data);
  return result;
}

/** List applications with pagination and optional status filter. */
export async function listApplications(
  page = 1,
  pageSize = 20,
  status?: string,
): Promise<ApplicationListResponse> {
  const params: Record<string, string | number> = { page, page_size: pageSize };
  if (status) params['status'] = status;
  const { data } = await api.get<ApplicationListResponse>('/applications/', { params });
  return data;
}

/** Get a single application by ID. */
export async function getApplication(appId: string): Promise<Application> {
  const { data } = await api.get<Application>(`/applications/${appId}`);
  return data;
}

/** Approve a pending application for automated submission. */
export async function approveApplication(appId: string): Promise<Application> {
  const { data } = await api.put<Application>(`/applications/${appId}/approve`);
  return data;
}

/** Deliver a user's CAPTCHA/2FA response to the worker waiting on an intervention. */
export async function resolveIntervention(appId: string, response: string): Promise<{ resolved: boolean }> {
  const { data } = await api.post<{ resolved: boolean }>(`/applications/${appId}/intervention`, { response });
  return data;
}

/** Re-queue (headed) an application paused for a CAPTCHA/verification wall, once the
 *  operator has cleared it themselves in the browser window that opened for it. */
export async function resolveBlocker(appId: string): Promise<{ queued: boolean }> {
  const { data } = await api.post<{ queued: boolean }>(`/applications/${appId}/resolve-blocker`);
  return data;
}

/** Approve and enqueue a set of staged applications together. Returns the count approved. */
export async function bulkApprove(applicationIds: string[]): Promise<{ approved: number }> {
  const { data } = await api.post<{ approved: number }>('/applications/bulk-approve', {
    application_ids: applicationIds,
  });
  return data;
}

/** Update an application's status. */
export async function updateApplicationStatus(
  appId: string,
  update: ApplicationStatusUpdate,
): Promise<Application> {
  const { data } = await api.put<Application>(`/applications/${appId}/status`, update);
  return data;
}

/**
 * Everything needed to prove what happened to one application: job, submission, documents,
 * account, run log and failure detail. Sections that were never recorded come back flagged,
 * so the panel can say "Not recorded" rather than render a convincing blank.
 */
export async function getApplicationEvidence(appId: string): Promise<ApplicationEvidence> {
  const { data } = await api.get<ApplicationEvidence>(`/applications/${appId}/evidence`);
  return data;
}

/** Generate (LLM) and store a cover letter for the application's job + résumé. */
export async function generateCoverLetter(appId: string): Promise<CoverLetterResponse> {
  const { data } = await api.post<CoverLetterResponse>(`/applications/${appId}/cover-letter`);
  return data;
}

/** Whether the agent can apply to this job right now, and what's missing if not. */
export async function getApplyReadiness(jobId: string, resumeId?: string): Promise<ApplyReadiness> {
  const { data } = await api.get<ApplyReadiness>(`/applications/readiness/${jobId}`, {
    params: resumeId ? { resume_id: resumeId } : undefined,
  });
  return data;
}

/**
 * ATS match for every row in one request. Rows with a résumé attached are scored with it (and the
 * score is saved); the rest are scored with the best-matching base résumé. Omit `applicationIds`
 * to score everything waiting for review.
 */
export async function scoreApplications(
  applicationIds?: string[],
  resumeId?: string,
): Promise<ApplicationScoreResponse> {
  const { data } = await api.post<ApplicationScoreResponse>('/applications/score', {
    application_ids: applicationIds ?? null,
    resume_id: resumeId ?? null,
  });
  return data;
}

/** Tailor a résumé for one application, attach it, and return the file's own ATS score. */
export async function tailorApplication(
  appId: string,
  body: ApplicationTailorRequest = {},
): Promise<ApplicationTailorResponse> {
  // Generation reads a PDF, calls the model, edits the file and checks it — well past the
  // client's default timeout, which would otherwise report a failure for work that completes.
  const { data } = await api.post<ApplicationTailorResponse>(`/applications/${appId}/tailor`, body, {
    timeout: 180_000,
  });
  return data;
}
