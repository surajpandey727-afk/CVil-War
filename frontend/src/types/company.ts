/**
 * Company profile. Mirrors the backend `CompanyProfile`.
 *
 * Shaped around the fact that under the zero-cost constraint most company data is genuinely
 * unobtainable: `unavailable_fields` names what could not be established, so the UI states it
 * rather than rendering blanks that look like a thin profile.
 */

export interface CompanyJob {
  job_id: string;
  title: string;
  location: string;
  url: string;
}

export interface CompanyProfile {
  name: string;
  /** False when nothing beyond the name is known. */
  available: boolean;
  /** The employer's own site. Never guessed from the name. */
  website: string | null;
  website_source: string;
  industry: string | null;
  description: string | null;
  source: string;
  other_jobs: CompanyJob[];
  other_jobs_count: number;
  unavailable_fields: string[];
  unavailable_reason: string;
}
