/** GET /api/v1/applications/{id}/pack — everything needed to apply by hand. */
export interface PackAnswer {
  question: string;
  answer: string;
  /** "add_only_if_true" answers are placeholders or drafts the CV doesn't evidence. */
  evidence_status: 'supported' | 'add_only_if_true' | string;
  note: string;
}

export interface ApplyPack {
  application_id: string;
  job_title: string;
  company: string;
  employer_url: string | null;
  location: string | null;
  manual_reason: string | null;
  cv: { name: string; download_path: string } | null;
  has_cover_letter: boolean;
  fit_overall: number | null;
  answers: PackAnswer[];
  checklist: string[];
}
