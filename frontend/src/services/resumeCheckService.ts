import api, { LLM_CALL_TIMEOUT_MS } from './api';
import type { ResumeCheckRequest, ResumeCheckResponse, ResumeReviewResponse } from '@/types/resumeCheck';

/** The deterministic check: score, evidence, gaps, sections, rule-based rewrites. Fast. */
export async function checkResume(body: ResumeCheckRequest): Promise<ResumeCheckResponse> {
  const { data } = await api.post<ResumeCheckResponse>('/resume-checker/check', body);
  return data;
}

/** The Claude review layered on top — a real LLM call, so it gets the long timeout. */
export async function reviewResume(body: ResumeCheckRequest): Promise<ResumeReviewResponse> {
  const { data } = await api.post<ResumeReviewResponse>('/resume-checker/review', body, {
    timeout: LLM_CALL_TIMEOUT_MS,
  });
  return data;
}
