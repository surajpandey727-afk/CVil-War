import type { PaginatedResponse } from './api';

/**
 * A single job listing from any platform.
 * Corresponds to the backend `JobListingResponse` Pydantic schema.
 */
export interface Job {
  /** Structured intelligence lifted from the posting; null until it has been fetched. */
  posting_data?: {
    criteria?: Record<string, string>;
    requirements?: string[];
    benefits?: string[];
    years_required?: number | null;
    word_count?: number;
    requirement_count?: number;
    benefit_count?: number;
    source?: string;
  } | null;
  /** When the full posting was fetched. Null means never — not "it has no requirements". */
  enriched_at?: string | null;
  id: string;
  platform: string;
  platform_job_id: string;
  title: string;
  company: string;
  location: string;
  url: string;
  /** Where the form is, when the source distinguishes it from the advert. */
  application_url?: string | null;
  description: string;
  salary_range: string | null;
  job_type: string | null;
  remote: boolean;
  posted_date: string | null;
  experience_level: string | null;
  match_score: number | null;
  skills_required: Record<string, unknown> | null;
  status: string;
  created_at: string;
  updated_at: string;
  /** How confident the system is this employer sponsors the Skilled Worker visa. */
  sponsor_confidence: SponsorConfidence;
  /** The matched register entry name, or the posting phrase that triggered detection. */
  sponsor_evidence: string | null;
}

/** Mirrors the backend `SponsorConfidence` enum. */
export type SponsorConfidence =
  | 'confirmed_register'
  | 'keyword_detected'
  | 'likely'
  | 'unknown'
  | 'not_sponsor';

/** Alias matching the backend schema name `JobListingResponse`. */
export type JobListingResponse = Job;

/** Request body for multi-platform job search. */
export interface JobSearchRequest {
  query: string;
  location?: string;
  platforms?: string[];
  filters?: Record<string, unknown>;
  limit?: number;
}

/** Paginated list of job listings. */
export type JobListResponse = PaginatedResponse<Job>;

/** Response from the job analysis endpoint. */
export interface JobAnalysisResponse {
  job_id: string;
  match_score: number;
  skill_match: number;
  keyword_match: number;
  missing_skills: string[];
  suggestions: string[];
}
