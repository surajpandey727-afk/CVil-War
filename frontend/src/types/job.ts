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

  /* -- Canonical, filterable form of the facts candidates filter on -------------------
   *
   * Derived on the server by `app.core.salary` and `app.schemas.job.sponsorship_status`, so
   * the filter, the sort and the card read the same numbers instead of each parsing
   * `salary_range` themselves. They used to, and disagreed: the card read "Up to £60,000 +
   * 10% bonus" as £60,000 while the filter read it as £10,000 and hid the row.
   *
   * Optional only because a stored response from before this shipped will not carry them.
   * Absent means "no band recoverable", which is the same thing the parser says about
   * "Competitive" — never £0, which would hide every job that does not advertise pay. */
  /** Annual, in `salary_currency`. Null when the posting published no floor. */
  salary_min?: number | null;
  /** Annual, in `salary_currency`. Null when the posting published no ceiling. */
  salary_max?: number | null;
  /** ISO code, when the posting marked one. Never assumed to be GBP. */
  salary_currency?: string | null;
  /** `year` unless the posting quoted a day, hour or monthly rate. */
  salary_period?: string | null;
  /** True when the figures were converted from a day/hour/monthly rate rather than quoted. */
  salary_annualised?: boolean;
  /** The three states a visa-dependent candidate needs to tell apart. */
  sponsorship_status?: SponsorshipStatus;
}

/** Mirrors the backend `SponsorshipStatus` literal in `app/schemas/job.py`.
 *
 *  Three values, not the five evidence grades of `SponsorConfidence`: "how do we know" is a
 *  different question from "can I take this job", and only the second one is a filter. */
export type SponsorshipStatus = 'available' | 'not_specified' | 'none';

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
