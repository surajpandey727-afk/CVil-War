/**
 * The "where, when, how" line at the top of every job card and the drawer:
 *
 *     Employer · City, Country · Posted 3 Oct 2026 (21 days ago) · Hybrid
 *
 * Each part is read from a server-derived field (see backend `app.core.geo.classify` and
 * `app.core.dates`), never re-parsed here, and each says plainly when it is unknown instead of
 * substituting something else. In particular the posting date is never replaced by the date
 * CVil-War discovered the job: those are different facts, and showing one as the other is the
 * fabricated date the product must not display.
 */
import type { Job, WorkplaceType } from '@/types/job';

/** "London, United Kingdom", "United Kingdom" (UK-wide), or the raw text as a last resort. */
export function placeLabel(job: Job): string {
  const country = job.country_name ?? (job.country_code === 'GB' ? 'United Kingdom' : null);
  if (job.city && country) return `${job.city}, ${country}`;
  if (country) return country;
  return job.location?.trim() || 'Location not stated';
}

export const WORKPLACE_LABEL: Record<WorkplaceType, string> = {
  onsite: 'On-site',
  hybrid: 'Hybrid',
  remote: 'Remote',
  unspecified: 'Arrangement not stated',
};

export function workplaceOf(job: Job): WorkplaceType {
  if (job.workplace_type) return job.workplace_type;
  return job.remote ? 'remote' : 'unspecified';
}

const DAY_MS = 86_400_000;

export interface PostedInfo {
  /** False when the source published no posting date. */
  known: boolean;
  /** "Posted 3 Oct 2026" or "Posting date unavailable". */
  label: string;
  /** "21 days ago" / "today" — empty when unknown. */
  ago: string;
  /** Whole days since posting; null when unknown. */
  days: number | null;
}

/** The posting date, exactly as the source stated it — or an explicit "unavailable". */
export function postedInfo(job: Job, now: Date = new Date()): PostedInfo {
  const raw = job.posted_at ?? job.posted_date;
  const when = raw ? new Date(raw) : null;
  if (!when || Number.isNaN(when.getTime())) {
    return { known: false, label: 'Posting date unavailable', ago: '', days: null };
  }
  const days = Math.max(0, Math.floor((now.getTime() - when.getTime()) / DAY_MS));
  const date = when.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  const ago = days === 0 ? 'today' : days === 1 ? '1 day ago' : `${days} days ago`;
  return { known: true, label: `Posted ${date}`, ago, days };
}
