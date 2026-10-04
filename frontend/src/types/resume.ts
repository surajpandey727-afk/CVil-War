/**
 * A stored resume record.
 * Corresponds to the backend `ResumeResponse` Pydantic schema.
 */
export interface Resume {
  id: string;
  name: string;
  type: string;
  template_id: string;
  base_resume_id: string | null;
  job_id: string | null;
  has_pdf: boolean;
  has_docx: boolean;
  ats_score: number | null;
  /** What a tailoring pass changed, checked and scored. Null for uploaded résumés. */
  tailoring_audit?: TailoringAudit | null;
  /** Applications this CV is attached to, and how many of those actually went out. */
  used_in_applications: number;
  submitted_applications: number;
  /** Kept for the record after being sent to an employer, hidden from the working list. */
  archived: boolean;
  created_at: string;
  updated_at: string;
}

/** One edited paragraph, with the evidence the edit rests on. */
export interface TailoringChange {
  line_id: string;
  section: string;
  before_text: string;
  /** Empty when the line was removed to meet the pagination rules. */
  after_text: string;
  /** "modified", or "removed" for a bullet cut because it added least to this job. */
  change_type?: string;
  reason: string;
  evidence: string;
  keywords_added: string[];
  /** "Current résumé", or the trusted sources a recovered fact was taken from. */
  evidence_sources?: string[];
  /** Words or figures this edit surfaced that the current résumé did not contain. */
  recovered_terms?: string[];
}

/** One finding of the ATS evaluation: a requirement, how well the résumé evidences it, and where. */
export interface EvaluationFinding {
  requirement: string;
  tier: string;
  type: string;
  strength: string;
  evidence: string;
  location: string;
  note: string;
}

/** The ATS + shortlist evaluation of one résumé file against one posting (scores 0–100). */
export interface AtsEvaluation {
  ats_match: number;
  parsing: number;
  shortlist: number;
  band: string;
  shortlist_band: string;
  components: Record<string, number>;
  tiers: Record<string, { matched: number; mentioned: number; total: number }>;
  strongest: EvaluationFinding[];
  weak: EvaluationFinding[];
  missing: EvaluationFinding[];
  problems: { what: string; where: string; why: string; effect: string; priority: string }[];
  recruiter: { signal: string; reasons: string[] };
  verdict: { ats_alignment: string; human_review: string; why: string[]; holding_back: string[]; tailoring_limit: string };
  parsing_findings: string[];
  constrained_by: string[];
}

export interface PaginationRule {
  rule: string;
  ok: boolean;
  applicable: boolean;
  detail: string;
}

/** What the pagination stage did and whether each hard layout rule holds in the final file. */
export interface PaginationReport {
  status: 'compliant' | 'reflowed' | 'condensed' | 'suppressed' | 'not_met' | 'skipped' | 'not_applied';
  reason?: string;
  deficit_points?: number | null;
  before?: { pages: number; ok: boolean; rules: PaginationRule[] };
  after?: { pages: number; ok: boolean; rules: PaginationRule[] };
  condense_rounds?: { round: number; lines_needed: number; proposed: number; applied?: number; outcome?: string }[];
}

/**
 * The account of one tailoring pass (backend `tailoring_audit`). ATS figures are 0–100 here —
 * the engine's own scale — unlike `Resume.ats_score`, which is 0–1.
 */
export interface TailoringAudit {
  /** "generated" = at least one edit was written into the PDF; "unchanged" = none was justified. */
  generation_status?: 'generated' | 'unchanged';
  validation_status?: string;
  mode?: string;
  formatting_preserved?: boolean;
  original_ats_score: number;
  final_ats_score: number;
  /** True when the final score was computed by re-reading the generated PDF. */
  ats_scored_from?: string;
  keywords_added: string[];
  keywords_not_added: string[];
  reason_not_added?: string;
  changes: TailoringChange[];
  rejected_edits: { line_id: string; rule: string; detail: string }[];
  skipped?: { line_id: string; reason: string }[];
  checks?: { ok: boolean; problems: string[]; pages?: number; pixels_changed_outside_edits?: number };
  structure_unchanged?: boolean;
  trusted_sources_consulted?: string[];
  substituted_fonts?: string[];
  claims_added?: number;
  fabrication_check?: string;
  generated_at?: string;
  job_id?: string;
  base_resume_id?: string;
  /** The ATS score the loop works toward, whether it was reached, and why not when it was not. */
  ats_target?: number;
  ats_target_reached?: boolean;
  ats_target_note?: string;
  rounds?: { round: number; focus: string[]; proposed: number; applied?: number; ats_after?: number; outcome: string }[];
  evaluation_before?: AtsEvaluation | null;
  evaluation_after?: AtsEvaluation | null;
  pagination?: PaginationReport;
}

/** Alias matching the backend schema name `ResumeResponse`. */
export type ResumeResponse = Resume;

/** One application a résumé was attached to. */
export interface ResumeUsageItem {
  application_id: string;
  job_title: string;
  company: string;
  status: string;
  /** True when this one reached the employer. Drafts are disposable; sent ones are records. */
  submitted: boolean;
  applied_at: string | null;
  ats_score: number | null;
}

export interface ResumeUsageResponse {
  resume_id: string;
  total: number;
  submitted: number;
  items: ResumeUsageItem[];
}

/**
 * What actually happened to a résumé the user asked to remove.
 *
 * Deleting and archiving are reported separately because they are different outcomes: a user
 * who asked to delete and got an archive is owed the reason, and a UI that cannot tell them
 * apart will say the wrong thing.
 */
export interface ResumeDeleteResponse {
  resume_id: string;
  deleted: boolean;
  archived: boolean;
  used_by: number;
  detail: string;
}

/** What "fill in my profile from this résumé" found and did. */
export interface ExtractProfileResponse {
  resume_id: string;
  experience_found: number;
  education_found: number;
  /** False when the profile already had work history and was left unchanged. */
  profile_updated: boolean;
  detail: string;
}

/** Response after uploading a resume file. */
export interface ResumeUploadResponse {
  id: string;
  name: string;
  file_format: string;
  word_count: number;
  skills_detected: string[];
}

/** ATS score breakdown for a resume against a job. */
export interface ResumeScoreResponse {
  resume_id: string;
  job_id: string;
  overall_score: number;
  skill_score: number;
  experience_score: number;
  education_score: number;
  keyword_score: number;
  missing_skills: string[];
  suggestions: string[];
}

/** One résumé line the AI reviewer judged weak, with a concrete rewrite. */
export interface WeakBullet {
  original: string;
  why_weak: string;
  rewrite: string;
}

/** The on-demand LLM read: semantic skill matching, recency, seniority, bullet rewrites —
 *  everything the always-on algorithmic score (above) can't do. */
export interface LLMAtsReview {
  semantic_score: number;
  contextually_satisfied_skills: string[];
  still_missing_skills: string[];
  recency_note: string;
  seniority_note: string;
  weak_bullets: WeakBullet[];
  verdict: string;
}

export interface ResumeAtsReviewResponse {
  resume_id: string;
  job_id: string;
  review: LLMAtsReview | null;
  /** False when no LLM was reachable — render "unavailable", not an empty review. */
  available: boolean;
  detail: string;
}

/** Request to score a resume against a job listing. */
export interface ResumeScoreRequest {
  job_id: string;
}

/** Request to generate a tailored resume. */
export interface ResumeGenerateRequest {
  base_resume_id: string;
  job_id: string;
  template_id?: string;
  output_formats?: string[];
  /** Make another version even though one already exists for this résumé and job. */
  regenerate?: boolean;
}

/** Paginated list of resumes. */
export interface ResumeListResponse {
  items: Resume[];
  total: number;
  /** Archived CVs held back from `items`, so the UI can offer to show them. */
  archived_count: number;
}
