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
  /** Applications this CV is attached to, and how many of those actually went out. */
  used_in_applications: number;
  submitted_applications: number;
  /** Kept for the record after being sent to an employer, hidden from the working list. */
  archived: boolean;
  created_at: string;
  updated_at: string;
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
}

/** Paginated list of resumes. */
export interface ResumeListResponse {
  items: Resume[];
  total: number;
  /** Archived CVs held back from `items`, so the UI can offer to show them. */
  archived_count: number;
}
