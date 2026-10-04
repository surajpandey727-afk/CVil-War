import type { Application } from './application';
import type { Resume } from './resume';

/** Requirements matched / merely listed / total, for one tier of a posting. */
export interface TierSummary {
  matched: number;
  mentioned: number;
  total: number;
}

/**
 * The headline of one résumé-versus-job ATS evaluation. Scores are 0–1 on the wire (multiply by
 * 100 to display, `atsPercent`).
 */
export interface MatchSummary {
  ats_match: number;
  parsing: number;
  shortlist: number;
  band: string;
  shortlist_band: string;
  tiers: Record<string, TierSummary>;
  /** Critical requirements the résumé has no evidence for. */
  top_gaps: string[];
  constrained_by: string[];
  recruiter_signal: string;
  tailoring_limit: string;
}

export interface ScoredWith {
  resume_id: string;
  resume_name: string;
  /** "attached" = the application's own résumé; "best" = the best-matching base résumé; "chosen" = picked. */
  source: 'attached' | 'best' | 'chosen';
}

export interface ApplicationScoreItem {
  application_id: string;
  job_id: string;
  scored: boolean;
  /** Why nothing was scored — shown instead of a made-up number. */
  reason: string;
  ats_score: number | null;
  persisted: boolean;
  scored_with: ScoredWith | null;
  summary: MatchSummary | null;
}

export interface ApplicationScoreResponse {
  items: ApplicationScoreItem[];
  scored: number;
  skipped: number;
}

export interface JobScoreItem {
  job_id: string;
  scored: boolean;
  reason: string;
  match_score: number | null;
  scored_with: ScoredWith | null;
  top_gaps: string[];
}

export interface JobScoreResponse {
  items: JobScoreItem[];
  scored: number;
  skipped: number;
}

export interface ApplicationTailorRequest {
  base_resume_id?: string | null;
  regenerate?: boolean;
}

export interface ApplicationTailorResponse {
  application: Application;
  resume: Resume;
  /** 0–1: the base résumé's ATS match, and the tailored file's — both from the files themselves. */
  ats_before: number | null;
  ats_after: number | null;
  status: string;
  target_note: string;
  summary: MatchSummary | null;
}

/** Where one row is in a bulk tailoring run. */
export type TailorRowState =
  | { phase: 'queued' }
  | { phase: 'running' }
  | { phase: 'done'; before: number | null; after: number | null; status: string; note: string; resumeName: string }
  | { phase: 'failed'; message: string };
