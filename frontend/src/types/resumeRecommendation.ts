/** Mirrors the backend `ResumeRecommendation` schema — which CV best fits a job, and why. */

import type { ResumeScoreResponse } from './resume';

export interface ResumeRanking {
  resume_id: string;
  resume_name: string;
  score: ResumeScoreResponse;
}

export interface ResumeRecommendation {
  job_id: string;
  /** `null` only when the user has no résumés at all. */
  recommended_resume_id: string | null;
  rankings: ResumeRanking[];
  /** One short paragraph: who wins, by how much, and what to change. */
  synopsis: string;
}
