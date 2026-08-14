/**
 * Job-vs-CV fit analysis. Mirrors the backend `FitAnalysis` schema.
 *
 * Two shapes encode promises the UI must keep. `categories` contains only dimensions the
 * posting actually supplied — a category absent from the list was not scored, and
 * `not_assessed` says why. And `evidence` is verbatim CV text, verified server-side against
 * the CV before it was sent; rendering it as a quotation is therefore safe.
 */

export type MatchLevel = 'excellent' | 'strong' | 'partial' | 'weak' | 'missing';

export type EvidenceSourceKey =
  | 'experience' | 'skills' | 'education' | 'summary'
  | 'certifications' | 'projects' | 'unattributed';

export interface RequirementMatch {
  requirement: string;
  level: MatchLevel;
  /** Verbatim CV text. Empty when the level is `missing`. */
  evidence: string;
  source: EvidenceSourceKey | null;
  /** The employer or institution the evidence sits under, when attributable. */
  source_detail: string;
  /** True when matched on meaning rather than the literal word, so it can be sanity-checked. */
  semantic: boolean;
  /** null when the posting does not distinguish must-have from nice-to-have. */
  required: boolean | null;
}

export interface FitCategory {
  key: string;
  label: string;
  score: number;
  rationale: string;
  /** How the number was arrived at — answers "where did this come from". */
  method: string;
}

export interface Recommendation {
  text: string;
  kind: 'add_evidence' | 'strengthen' | 'reword' | 'quantify' | 'cannot_evidence' | string;
  requirement: string;
  /** What in the CV this builds on. Empty only for `cannot_evidence`. */
  grounded_in: string;
}

export interface FitAnalysis {
  job_id: string;
  resume_id: string;
  resume_name: string;
  overall: number;
  categories: FitCategory[];
  /** Dimensions deliberately not scored, with the reason. */
  not_assessed: string[];
  matches: RequirementMatch[];
  recommendations: Recommendation[];
  /** `llm` or `keyword` — a degraded analysis must never look like a full one. */
  method: string;
  model: string;
  analysed_at: string | null;
  cached: boolean;
  /** Set when the stored analysis used a different CV than the one now selected. */
  stale_reason: string;
}
