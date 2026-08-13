/** Command centre types — mirror of `app/schemas/command_centre.py`. */

export type NextAction =
  | 'respond_to_recruiter' | 'complete_assessment' | 'upload_cv' | 'upload_document'
  | 'relogin' | 'complete_verification' | 'confirm_application' | 'review_answer'
  | 'follow_up' | 'schedule_interview' | 'prepare_interview' | 'review_application'
  | 'verify_submission' | 'resume_application' | 'update_profile' | 'wait' | 'none';

export type ActionPriority = 'high' | 'medium' | 'low' | 'none';

export type ApplicationHealth =
  | 'healthy' | 'needs_attention' | 'blocked' | 'stale'
  | 'session_required' | 'document_required' | 'action_required' | 'status_unknown';

export interface ActionItem {
  application_id: string;
  job_id: string;
  title: string;
  company: string;
  action: NextAction;
  priority: ActionPriority;
  /** Plain-English justification, rendered verbatim so the ranking can be sanity-checked. */
  reason: string;
  score: number;
  due_at: string | null;
  health: ApplicationHealth;
  status: string;
  /** Which surface resolves this action, so a click lands on the exact thing to do. */
  target: string;
  application_url: string | null;
  portal: string | null;
}

export interface ActionQueue {
  items: ActionItem[];
  total: number;
  by_priority: Record<string, number>;
}

export interface CommandCentreSummary {
  total_applications: number;
  needs_attention: number;
  high_priority: number;
  by_status: Record<string, number>;
  /** Operational health, NOT the hiring status — an application can be at interview and
   *  simultaneously blocked on an expired session. */
  by_health: Record<string, number>;
  upcoming_interviews: number;
  pending_assessments: number;
  top_actions: ActionItem[];
}

export interface TimelineEntry {
  id: string;
  event_type: string;
  occurred_at: string;
  summary: string;
  detail: string | null;
  actor: string;
  payload: Record<string, unknown> | null;
}

export interface ApplicationTimeline {
  application_id: string;
  entries: TimelineEntry[];
  total: number;
  current_action: NextAction;
  current_reason: string;
}

/** Label + colour per action. Colours are semantic tokens, never literals. */
export const ACTION_META: Record<NextAction, { label: string; cta: string }> = {
  complete_assessment: { label: 'Assessment due', cta: 'Open assessment' },
  prepare_interview: { label: 'Interview upcoming', cta: 'Prepare' },
  relogin: { label: 'Session expired', cta: 'Reconnect & resume' },
  complete_verification: { label: 'Verification required', cta: 'Complete verification' },
  resume_application: { label: 'Application paused', cta: 'Resume' },
  upload_cv: { label: 'CV required', cta: 'Choose CV' },
  upload_document: { label: 'Document required', cta: 'Upload' },
  review_application: { label: 'Awaiting your review', cta: 'Review' },
  review_answer: { label: 'Answer needs review', cta: 'Review answer' },
  confirm_application: { label: 'Confirmation required', cta: 'Confirm' },
  verify_submission: { label: 'Submission unconfirmed', cta: 'Verify' },
  follow_up: { label: 'Follow-up recommended', cta: 'Follow up' },
  respond_to_recruiter: { label: 'Recruiter waiting', cta: 'Reply' },
  schedule_interview: { label: 'Interview to schedule', cta: 'Schedule' },
  update_profile: { label: 'Profile out of date', cta: 'Update' },
  wait: { label: 'In progress', cta: 'View' },
  none: { label: 'No action', cta: 'View' },
};

export const PRIORITY_COLOR: Record<ActionPriority, string> = {
  high: 'var(--rejected)',
  medium: 'var(--review)',
  low: 'var(--accent)',
  none: 'var(--text-4)',
};
