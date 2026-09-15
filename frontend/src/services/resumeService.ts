import api from './api';
import type {
  Resume,
  ResumeDeleteResponse,
  ResumeUploadResponse,
  ResumeScoreResponse,
  ResumeGenerateRequest,
  ResumeListResponse,
  ResumeUsageResponse,
  ExtractProfileResponse,
} from '@/types/resume';

/** Upload a PDF or DOCX resume file. */
export async function uploadResume(file: File): Promise<ResumeUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post<ResumeUploadResponse>('/resumes/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

/** List all uploaded and generated resumes. */
export async function listResumes(): Promise<ResumeListResponse> {
  const { data } = await api.get<ResumeListResponse>('/resumes/');
  return data;
}

/** Generate a job-tailored resume from a base resume. */
export async function generateResume(request: ResumeGenerateRequest): Promise<Resume> {
  const { data } = await api.post<Resume>('/resumes/generate', request);
  return data;
}

/** Score a resume's ATS compatibility against a specific job. */
export async function scoreResume(
  resumeId: string,
  jobId: string,
): Promise<ResumeScoreResponse> {
  const { data } = await api.post<ResumeScoreResponse>(`/resumes/${resumeId}/score`, {
    job_id: jobId,
  });
  return data;
}

/** Optimize a resume for ATS keyword matching. */
export async function optimizeResume(resumeId: string): Promise<Resume> {
  const { data } = await api.post<Resume>(`/resumes/${resumeId}/optimize`);
  return data;
}

/**
 * Download a resume file. The endpoint streams a bearer-gated FileResponse, so a plain link
 * can't authenticate — fetch it through the api client (which attaches the token) as a blob
 * and hand it to the browser via a transient object URL.
 */
export async function downloadResumeFile(
  resumeId: string,
  format: 'pdf' | 'docx',
  name: string,
): Promise<void> {
  const { data } = await api.get<Blob>(`/resumes/${resumeId}/download`, {
    params: { format },
    responseType: 'blob',
  });
  const url = URL.createObjectURL(data);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Fetch a resume's PDF as a transient object URL for inline preview (an <iframe> src), as
 * opposed to downloadResumeFile's save-to-disk flow. Caller must URL.revokeObjectURL it.
 */
export async function fetchResumePreviewUrl(resumeId: string): Promise<string> {
  const { data } = await api.get<Blob>(`/resumes/${resumeId}/download`, {
    params: { format: 'pdf' },
    responseType: 'blob',
  });
  return URL.createObjectURL(data);
}

/** Fill in the account's work history/education from this résumé's text (ATS scoring needs
 *  real structured data for both — see the backend service docstring). No-op if the profile
 *  already has work history. */
export async function extractProfile(resumeId: string): Promise<ExtractProfileResponse> {
  const { data } = await api.post<ExtractProfileResponse>(`/resumes/${resumeId}/extract-profile`);
  return data;
}

/** Where a résumé has been used, so removing it is an informed decision. */
export async function getResumeUsage(resumeId: string): Promise<ResumeUsageResponse> {
  const { data } = await api.get<ResumeUsageResponse>(`/resumes/${resumeId}/usage`);
  return data;
}

/**
 * Remove a résumé. The backend deletes an unused one outright and archives one that has been
 * sent to an employer, so the response says which happened rather than assuming.
 */
export async function deleteResume(resumeId: string): Promise<ResumeDeleteResponse> {
  const { data } = await api.delete<ResumeDeleteResponse>(`/resumes/${resumeId}`);
  return data;
}
