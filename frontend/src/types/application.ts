import type { PaginatedResponse } from './api';

/**
 * A single job application record.
 * Corresponds to the backend `ApplicationResponse` Pydantic schema.
 */
export interface Application {
  id: string;
  job_id: string;
  job_title: string | null;
  company: string | null;
  resume_id: string | null;
  /** Which CV actually went out. An id alone cannot answer "what did they receive". */
  resume_name: string | null;
  resume_type: string | null;
  resume_ats_score: number | null;
  /** True when that CV has since been archived. The application still points at it. */
  resume_archived: boolean;
  has_cover_letter: boolean;
  status: string;
  apply_mode: string;
  ats_score: number | null;
  cover_letter_path: string | null;
  applied_at: string | null;
  response_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

/** Alias matching the backend schema name `ApplicationResponse`. */
export type ApplicationResponse = Application;

/** Request to create a single application. */
export interface ApplicationCreate {
  job_id: string;
  resume_id?: string | null;
  apply_mode?: string;
}

/** Request to create multiple applications at once. */
export interface ApplicationBatchCreate {
  job_ids: string[];
  resume_id?: string | null;
  apply_mode?: string;
}

/** Request to update an application's status. */
export interface ApplicationStatusUpdate {
  status: string;
  notes?: string | null;
  resume_id?: string | null;
}

/** Paginated list of applications. */
export type ApplicationListResponse = PaginatedResponse<Application>;
