/** Résumé checker contract — mirrors `backend/app/schemas/resume_check.py`.
 *
 *  Every score is 0–1 (the API convention); multiply by 100 to display (`atsPercent`).
 */

export type SectionKey = 'summary' | 'experience' | 'skills' | 'formatting';
export type EvidenceStatus = 'supported' | 'add_only_if_true';
export type FitBand = 'strong' | 'decent' | 'gap';

/** Exactly one target: a stored job, or a non-empty set of Skill Radar roles. */
export interface ResumeCheckRequest {
  resume_id: string;
  job_id?: string | null;
  role_titles?: string[];
}

export interface CheckTarget {
  kind: 'job' | 'roles';
  job_id?: string | null;
  title: string;
  company?: string | null;
  role_titles: string[];
}

export interface ScoreComponent {
  key: string;
  label: string;
  /** Share of the overall score; all weights sum to 1. */
  weight: number;
  score: number;
  detail: string;
}

export interface FitScore {
  overall: number;
  band: FitBand;
  components: ScoreComponent[];
  /** Human-readable, e.g. "0.45 × must-have + 0.20 × nice-to-have + …". */
  formula: string;
}

export interface Evidence {
  /** Verbatim résumé line — never paraphrased. */
  quote: string;
  section: string;
}

export interface MatchedSkill {
  key: string;
  label: string;
  category: string;
  must_have: boolean;
  evidence: Evidence[];
}

export interface MissingSkill {
  key: string;
  label: string;
  category: string;
  must_have: boolean;
  /** How many scanned UK-eligible jobs mention this skill. */
  uk_demand: number;
  uk_demand_share: number;
}

export interface AtsKeywords {
  coverage: number;
  total: number;
  found: string[];
  missing: string[];
}

export interface SectionReview {
  key: SectionKey;
  label: string;
  status: 'good' | 'needs_work' | 'missing';
  score: number;
  findings: string[];
}

export interface Suggestion {
  section: SectionKey;
  kind: 'rewrite' | 'add';
  /** The résumé line being rewritten (verbatim); absent for "add". */
  original?: string | null;
  suggested: string;
  reason: string;
  /** "add_only_if_true" whenever the text claims something the résumé does not evidence. */
  evidence_status: EvidenceStatus;
  source: 'rules' | 'llm';
}

export interface ResumeCheckResponse {
  resume_id: string;
  resume_name: string;
  target: CheckTarget;
  score: FitScore;
  matched_skills: MatchedSkill[];
  /** Already ranked: must-haves first, then by UK demand (most-asked first). */
  missing_skills: MissingSkill[];
  ats_keywords: AtsKeywords;
  sections: SectionReview[];
  suggestions: Suggestion[];
  corpus: { uk_jobs_scanned: number };
}

export interface SectionNote {
  section: SectionKey;
  note: string;
}

/** The Claude narrative layer on top of the deterministic check. */
export interface ResumeReviewResponse {
  available: boolean;
  /** Why it is unavailable (no key, provider error, invalid JSON). */
  detail?: string | null;
  model?: string | null;
  summary?: string | null;
  section_notes: SectionNote[];
  suggestions: Suggestion[];
  /** LLM suggestions dropped by validation (quote not in the résumé, …). */
  rejected_count: number;
}
