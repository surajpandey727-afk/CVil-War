/** Status + score presentation, mapped to the design's token palette. Shared by the
 *  pipeline table, status pills, and the app-detail drawer. */

export interface StatusMeta {
  label: string;
  color: string;
  soft: string;
}

const DEFAULT_STATUS: StatusMeta = { label: 'Queued', color: 'var(--q)', soft: 'var(--q-soft)' };

const STATUS: Record<string, StatusMeta> = {
  queued: DEFAULT_STATUS,
  pending_review: { label: 'Needs review', color: 'var(--review)', soft: 'var(--review-soft)' },
  approved: { label: 'Approved', color: 'var(--approved)', soft: 'var(--approved-soft)' },
  applying: { label: 'Applying', color: 'var(--accent)', soft: 'var(--accent-soft)' },
  applied: { label: 'Applied', color: 'var(--applied)', soft: 'var(--applied-soft)' },
  interview: { label: 'Interview', color: 'var(--interview)', soft: 'var(--interview-soft)' },
  offer: { label: 'Offer', color: 'var(--offer)', soft: 'var(--offer-soft)' },
  rejected: { label: 'Rejected', color: 'var(--rejected)', soft: 'var(--rejected-soft)' },
  withdrawn: { label: 'Withdrawn', color: 'var(--withdrawn)', soft: 'var(--q-soft)' },
  failed: { label: 'Failed', color: 'var(--failed)', soft: 'var(--failed-soft)' },
};

export function statusMeta(status: string): StatusMeta {
  return STATUS[status] ?? DEFAULT_STATUS;
}

/** A status is actionable (can be approved) when queued or awaiting review. */
export function isApprovable(status: string): boolean {
  return status === 'pending_review' || status === 'queued';
}

/** Mirrors the backend `SponsorConfidence` enum's tiers for display. */
const DEFAULT_SPONSOR: StatusMeta = { label: 'Sponsorship unknown', color: 'var(--q)', soft: 'var(--q-soft)' };

const SPONSOR: Record<string, StatusMeta> = {
  confirmed_register: { label: 'Sponsor confirmed', color: 'var(--offer)', soft: 'var(--offer-soft)' },
  keyword_detected: { label: 'Likely sponsor', color: 'var(--review)', soft: 'var(--review-soft)' },
  likely: { label: 'Likely sponsor', color: 'var(--review)', soft: 'var(--review-soft)' },
  unknown: DEFAULT_SPONSOR,
  not_sponsor: { label: 'Does not sponsor', color: 'var(--rejected)', soft: 'var(--rejected-soft)' },
};

/**
 * Present a job's `sponsor_confidence` for display. Never collapses "unknown" into a
 * false negative — see `SponsorConfidence`'s own docstring on why `not_sponsor` and
 * `unknown` are kept distinct.
 */
export function sponsorMeta(confidence: string | null | undefined): StatusMeta {
  return SPONSOR[confidence ?? ''] ?? DEFAULT_SPONSOR;
}

/** Mirrors the backend `JobStatus` enum (new/saved/applied/hidden) for the Jobs command
 *  centre's own palette — kept separate from `statusMeta` (application lifecycle) because
 *  they're different enums answering different questions: this is "what did the operator do
 *  with this listing", not "where is this application in the pipeline". Uses the jc- scoped
 *  tokens so it stays inside the Jobs page's own restrained palette rather than pulling in
 *  the app-wide accent. */
const JC_DEFAULT_JOB_STATUS: StatusMeta = { label: 'New', color: 'var(--jc-status-new)', soft: 'var(--jc-status-new-soft)' };

const JC_JOB_STATUS: Record<string, StatusMeta> = {
  new: JC_DEFAULT_JOB_STATUS,
  saved: { label: 'Saved', color: 'var(--jc-status-saved)', soft: 'var(--jc-status-saved-soft)' },
  applied: { label: 'Applied', color: 'var(--jc-status-applied)', soft: 'var(--jc-status-applied-soft)' },
  hidden: { label: 'Hidden', color: 'var(--jc-status-rejected)', soft: 'var(--jc-status-rejected-soft)' },
};

export function jobStatusMeta(status: string): StatusMeta {
  return JC_JOB_STATUS[status] ?? JC_DEFAULT_JOB_STATUS;
}

/** Sponsor-confidence presentation for the Jobs command centre's jc- scoped palette — same
 *  data as `sponsorMeta`, restated in tokens that stay inside this page's restrained
 *  army-green/brass/pewter system instead of the app-wide accent. */
const JC_DEFAULT_SPONSOR: StatusMeta = { label: 'Sponsorship unknown', color: 'var(--jc-text-3)', soft: 'var(--jc-status-new-soft)' };

const JC_SPONSOR: Record<string, StatusMeta> = {
  confirmed_register: { label: 'Sponsor confirmed', color: 'var(--jc-status-offer)', soft: 'var(--jc-status-offer-soft)' },
  keyword_detected: { label: 'Likely sponsor', color: 'var(--jc-status-review)', soft: 'var(--jc-status-review-soft)' },
  likely: { label: 'Likely sponsor', color: 'var(--jc-status-review)', soft: 'var(--jc-status-review-soft)' },
  unknown: JC_DEFAULT_SPONSOR,
  not_sponsor: { label: 'Does not sponsor', color: 'var(--jc-status-rejected)', soft: 'var(--jc-status-rejected-soft)' },
};

export function jcSponsorMeta(confidence: string | null | undefined): StatusMeta {
  return JC_SPONSOR[confidence ?? ''] ?? JC_DEFAULT_SPONSOR;
}

/**
 * Scale a 0–1 ATS/match score (as the API returns it) to a 0–100 integer for display.
 * Use this everywhere a score is shown or passed to {@link atsColor} — the raw 0–1 value
 * would otherwise render as "0"/"1" and always land in the rejected color band.
 */
export function atsPercent(score: number | null | undefined): number {
  return Math.round((score ?? 0) * 100);
}

/** ATS-score color band (offer / applied / review / rejected). Expects a 0–100 value. */
export function atsColor(score: number): string {
  if (score >= 85) return 'var(--offer)';
  if (score >= 75) return 'var(--applied)';
  if (score >= 65) return 'var(--review)';
  return 'var(--rejected)';
}

/** Compact relative time ("just now", "5m", "3h", "2d", or a short date). */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
