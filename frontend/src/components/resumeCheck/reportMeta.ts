/** Presentation tables shared by the résumé-checker report components. */
import type { FitBand, SectionKey, SectionReview } from '@/types/resumeCheck';

interface Tone {
  label: string;
  color: string;
  soft: string;
}

/** Same 60–70% "decent" bar as Skill Radar, so the two pages read a score the same way. */
export const BAND: Record<FitBand, Tone & { note: string }> = {
  strong: { label: 'Strong fit', color: 'var(--applied)', soft: 'var(--applied-soft)', note: 'You cover what this target screens for.' },
  decent: { label: 'Decent fit', color: 'var(--review)', soft: 'var(--review-soft)', note: 'Over the bar. Close the gaps below to pull clear.' },
  gap: { label: 'Real gap', color: 'var(--rejected)', soft: 'var(--rejected-soft)', note: 'Under the bar. The missing skills below matter most.' },
};

export const SECTION_STATUS: Record<SectionReview['status'], Tone> = {
  good: { label: 'Good', color: 'var(--applied)', soft: 'var(--applied-soft)' },
  needs_work: { label: 'Needs work', color: 'var(--review)', soft: 'var(--review-soft)' },
  missing: { label: 'Missing', color: 'var(--rejected)', soft: 'var(--rejected-soft)' },
};

/** Report order, top of the page to bottom. */
export const SECTION_ORDER: SectionKey[] = ['summary', 'experience', 'skills', 'formatting'];

export const SECTION_LABEL: Record<SectionKey, string> = {
  summary: 'Summary',
  experience: 'Experience bullets',
  skills: 'Skills',
  formatting: 'Formatting & ATS parsing',
};

/** Score-component colours: distinct tokens, no purple, in a fixed order so the bar and the
 *  ledger's swatches always agree. Cycles if the backend ever adds a sixth component. */
const SEGMENT = ['var(--accent)', 'var(--secondary)', 'var(--approved)', 'var(--applied)', 'var(--review)', 'var(--q)'];

export function segmentColor(i: number): string {
  return SEGMENT[i % SEGMENT.length] ?? 'var(--q)';
}
