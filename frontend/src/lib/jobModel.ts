/** The canonical reading of a job, shared by the filters, the sort and the cards.
 *
 *  Every one of those used to derive salary and sponsorship for itself. They disagreed, and
 *  the disagreement was invisible: a card reading "Up to £60,000 + 10% bonus" showed £60,000
 *  while the filter behind it read £10,000 and removed the row, so a candidate searching above
 *  £50k never saw a job that paid £60k and had no way to find out why.
 *
 *  The amounts themselves are parsed once, on the server (`app/core/salary.py`), and served on
 *  the job. Nothing is re-parsed here — a second parser in a second language is how the source
 *  catalogue in `lib/sources.ts` drifted out of sync with the backend registry for weeks. This
 *  module only reads the served fields and answers questions about them.
 */

import type { Job, SponsorshipStatus } from '@/types/job';

/** What the posting pays, annualised, or nulls when it published nothing.
 *
 *  `null` is not `0`. Most UK postings publish no salary at all, so treating an unpublished
 *  one as zero would hide the majority of the market behind any minimum-salary filter. */
export interface SalaryBand {
  min: number | null;
  max: number | null;
  currency: string | null;
  /** True when converted from a day, hour or monthly rate rather than quoted annually. */
  annualised: boolean;
  /** True when the posting published any figure at all. */
  published: boolean;
}

export function salaryBand(job: Job): SalaryBand {
  const min = job.salary_min ?? null;
  const max = job.salary_max ?? null;
  return {
    min,
    max,
    currency: job.salary_currency ?? null,
    annualised: job.salary_annualised ?? false,
    published: min !== null || max !== null,
  };
}

/** The status the sponsorship filter and the card badge both read.
 *
 *  Falls back to the evidence grade for a job stored before the server started deriving this,
 *  using the same mapping the server uses — one rule, written down twice only because old rows
 *  exist, not because two vocabularies do. */
export function sponsorshipStatus(job: Job): SponsorshipStatus {
  if (job.sponsorship_status) return job.sponsorship_status;
  switch (job.sponsor_confidence) {
    case 'confirmed_register':
    case 'keyword_detected':
    case 'likely':
      return 'available';
    case 'not_sponsor':
      return 'none';
    default:
      return 'not_specified';
  }
}

/**
 * How each sponsorship answer is worded.
 *
 * `chip` is the filter option and `card` is the fact on a job row, and they are deliberately
 * different strings. When both read "Not specified" the filter chip and the card pill became
 * indistinguishable to anything selecting by text — including the test suite, which matched
 * the filter chip and then asserted about the list before it had rendered, passing for the
 * wrong reason.
 */
export const SPONSORSHIP_META: Record<
  SponsorshipStatus,
  { label: string; chip: string; card: string; hint: string }
> = {
  available: {
    label: 'Sponsorship available',
    chip: 'Sponsors',
    card: 'Sponsored',
    hint: 'This employer is on the Home Office register, or the posting says it sponsors.',
  },
  not_specified: {
    label: 'Sponsorship not specified',
    chip: 'Not specified',
    card: 'Not stated',
    hint: 'The posting does not mention sponsorship. That is not a no — most postings never say.',
  },
  none: {
    label: 'No sponsorship',
    chip: 'No sponsorship',
    card: 'Not sponsored',
    hint: 'The posting states it will not sponsor a visa.',
  },
};

/** The brackets the filter offers, in thousands of the posting's own currency.
 *
 *  `max: null` is the open-ended top bracket. These are bands a candidate thinks in, not
 *  arbitrary slices: they match how UK postings are advertised. */
export interface SalaryBracket {
  id: string;
  label: string;
  /** Inclusive floor, in thousands. */
  minK: number;
  /** Exclusive ceiling, in thousands. `null` for the open-ended bracket. */
  maxK: number | null;
}

export const SALARY_BRACKETS: SalaryBracket[] = [
  { id: '20-30', label: '£20–30k', minK: 20, maxK: 30 },
  { id: '30-40', label: '£30–40k', minK: 30, maxK: 40 },
  { id: '40-50', label: '£40–50k', minK: 40, maxK: 50 },
  { id: '50-60', label: '£50–60k', minK: 50, maxK: 60 },
  { id: '60-75', label: '£60–75k', minK: 60, maxK: 75 },
  { id: '75+', label: '£75k+', minK: 75, maxK: null },
];

export const BRACKET_BY_ID: Record<string, SalaryBracket> = Object.fromEntries(
  SALARY_BRACKETS.map((b) => [b.id, b]),
);

/** Does a posting's band overlap the window `[minK, maxK)`?
 *
 *  Overlap, not containment. A role advertised at £55–£85k genuinely is a candidate for a
 *  "£60–75k" search — requiring the whole band to sit inside the bracket would drop exactly
 *  the wide, well-paid ranges a candidate most wants to see. */
export function overlapsWindow(band: SalaryBand, minK: number, maxK: number | null): boolean {
  if (!band.published) return false;
  const low = (band.min ?? band.max)! / 1000;
  const high = (band.max ?? band.min)! / 1000;
  if (high < minK) return false;
  if (maxK !== null && low >= maxK) return false;
  return true;
}

/** Does the posting match any of the selected brackets? Empty selection means no restriction. */
export function matchesBrackets(band: SalaryBand, bracketIds: string[]): boolean {
  if (!bracketIds.length) return true;
  return bracketIds.some((id) => {
    const bracket = BRACKET_BY_ID[id];
    return bracket ? overlapsWindow(band, bracket.minK, bracket.maxK) : false;
  });
}

/** Does the posting match a custom `£{minK}k–£{maxK}k` window? Nulls mean "unbounded". */
export function matchesCustomRange(
  band: SalaryBand,
  minK: number | null,
  maxK: number | null,
): boolean {
  if (minK === null && maxK === null) return true;
  return overlapsWindow(band, minK ?? 0, maxK);
}

/** A single formatted salary string for the card, in the posting's own currency. */
export function formatSalary(band: SalaryBand): string | null {
  if (!band.published) return null;
  const symbol = band.currency === 'USD' ? '$' : band.currency === 'EUR' ? '€' : '£';
  const k = (v: number) => `${symbol}${Math.round(v / 1000)}k`;
  if (band.min !== null && band.max !== null) {
    return band.min === band.max ? k(band.min) : `${k(band.min)}–${k(band.max)}`;
  }
  if (band.max !== null) return `Up to ${k(band.max)}`;
  return `From ${k(band.min!)}`;
}
