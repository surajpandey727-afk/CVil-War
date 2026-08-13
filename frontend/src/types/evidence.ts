/**
 * The application evidence bundle. Mirrors the backend `ApplicationEvidence` schema.
 *
 * Every section carries `recorded`. That is the contract: a section that was never captured
 * is absent, not empty, so the panel prints "Not recorded" instead of a blank that reads as
 * fact. Historical applications genuinely have no account and no logs.
 *
 * Nothing here is a credential. `account` is a masked label and a connection state.
 */

export interface EvidenceJob {
  recorded: boolean;
  job_id: string | null;
  title: string | null;
  company: string | null;
  location: string | null;
  salary: string | null;
  remote: boolean;
  /** The board this lives on: reed, linkedin, careers:monzo, … */
  source: string | null;
  /** Where the advert is. `null` means none was stored — never construct one. */
  job_url: string | null;
  /** Where the form is, and only when it genuinely differs from `job_url`. */
  application_url: string | null;
  posted_at: string | null;
}

export interface EvidenceSubmission {
  status: string;
  /** `null` on a sent application means the row predates run recording. */
  method: string | null;
  confirmation_state: string;
  confirmation_detail: string | null;
  external_reference: string | null;
  submitted_at: string | null;
  ats_score: number | null;
  apply_mode: string;
  origin: string;
  actor: string | null;
  recorded: boolean;
}

export interface EvidenceDocument {
  recorded: boolean;
  document_id: string | null;
  name: string | null;
  kind: string | null;
  ats_score: number | null;
  created_at: string | null;
  archived: boolean;
  has_pdf: boolean;
  has_docx: boolean;
}

export interface EvidenceCoverLetter {
  recorded: boolean;
  used: boolean;
  name: string | null;
  origin: string | null;
}

export interface EvidenceAccount {
  recorded: boolean;
  platform: string | null;
  /** Masked, e.g. `sur***@example.com`. */
  account: string | null;
  connected: boolean;
  state: string | null;
  detail: string | null;
  last_used_at: string | null;
}

export interface EvidenceLogEntry {
  at: string;
  /** `application` (lifecycle) or `automation` (browser agent steps). */
  source: string;
  kind: string;
  message: string;
  detail: string | null;
  actor: string | null;
}

export interface EvidenceFailure {
  message: string;
  failure_class: string | null;
  root_cause: string | null;
  failed_at: string | null;
  url: string | null;
  step_count: number | null;
  can_retry: boolean;
}

export interface ApplicationEvidence {
  application_id: string;
  job: EvidenceJob;
  submission: EvidenceSubmission;
  resume: EvidenceDocument;
  cover_letter: EvidenceCoverLetter;
  account: EvidenceAccount;
  failure: EvidenceFailure | null;
  log: EvidenceLogEntry[];
  log_recorded: boolean;
}
