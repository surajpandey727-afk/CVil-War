/** The canonical reading of a job — the one the filters, the sort and the cards all share.
 *
 *  These are the rules that stop a card and the filter behind it disagreeing about the same
 *  posting, which is what the whole module exists to prevent.
 */
import { describe, it, expect } from 'vitest';

import {
  SALARY_BRACKETS, formatSalary, matchesBrackets, matchesCustomRange, overlapsWindow,
  salaryBand, sponsorshipStatus,
} from '@/lib/jobModel';
import type { Job } from '@/types/job';

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 'j1', platform: 'reed', platform_job_id: 'r1', title: 'ML Engineer',
    company: 'Northwind', location: 'London', url: 'https://x', description: '',
    salary_range: null, job_type: null, remote: false, posted_date: null,
    experience_level: null, match_score: 0.8, skills_required: null, status: 'new',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    sponsor_confidence: 'unknown', sponsor_evidence: null,
    ...overrides,
  } as Job;
}

describe('salaryBand', () => {
  it('reads the figures the server derived', () => {
    const band = salaryBand(job({ salary_min: 60_000, salary_max: 80_000, salary_currency: 'GBP' }));
    expect(band).toMatchObject({ min: 60_000, max: 80_000, currency: 'GBP', published: true });
  });

  it('reports an unpublished salary as unpublished, never as zero', () => {
    // £0 and "not published" are different facts, and only one of them should be able to
    // exclude a job from a minimum-salary search.
    const band = salaryBand(job({ salary_range: 'Competitive' }));
    expect(band.published).toBe(false);
    expect(band.min).toBeNull();
    expect(band.max).toBeNull();
  });

  it('carries the annualised flag so a day rate is not passed off as a quoted figure', () => {
    expect(salaryBand(job({ salary_min: 110_000, salary_annualised: true })).annualised).toBe(true);
  });
});

describe('sponsorshipStatus', () => {
  it.each([
    ['confirmed_register', 'available'],
    ['keyword_detected', 'available'],
    ['likely', 'available'],
    ['unknown', 'not_specified'],
    ['not_sponsor', 'none'],
  ] as const)('maps %s to %s when the server did not', (confidence, expected) => {
    expect(sponsorshipStatus(job({ sponsor_confidence: confidence }))).toBe(expected);
  });

  it('prefers the value the server sent', () => {
    const j = job({ sponsor_confidence: 'unknown', sponsorship_status: 'available' });
    expect(sponsorshipStatus(j)).toBe('available');
  });

  it('silence is its own answer, not a no', () => {
    // A posting that never mentions sponsorship has not refused it. Collapsing the two would
    // hide most of the market from a candidate who needs a visa.
    expect(sponsorshipStatus(job({ sponsor_confidence: 'unknown' }))).not.toBe('none');
  });
});

describe('salary brackets', () => {
  const band = (min: number | null, max: number | null) =>
    salaryBand(job({ salary_min: min, salary_max: max }));

  it('matches a band that sits inside the bracket', () => {
    expect(matchesBrackets(band(52_000, 58_000), ['50-60'])).toBe(true);
  });

  it('matches a wide band that merely overlaps the bracket', () => {
    // £55–85k genuinely is a candidate for a "£60–75k" search. Requiring containment would
    // drop exactly the wide, well-paid ranges a candidate most wants to see.
    expect(matchesBrackets(band(55_000, 85_000), ['60-75'])).toBe(true);
  });

  it('rejects a band that falls entirely below the bracket', () => {
    expect(matchesBrackets(band(30_000, 38_000), ['50-60'])).toBe(false);
  });

  it('rejects a band that sits entirely above the bracket', () => {
    expect(matchesBrackets(band(90_000, 110_000), ['30-40'])).toBe(false);
  });

  it('the open-ended top bracket has no ceiling', () => {
    expect(matchesBrackets(band(250_000, 300_000), ['75+'])).toBe(true);
  });

  it('several brackets are an OR, not an AND', () => {
    expect(matchesBrackets(band(35_000, 38_000), ['30-40', '75+'])).toBe(true);
  });

  it('no bracket selected means no restriction', () => {
    expect(matchesBrackets(band(10_000, 12_000), [])).toBe(true);
  });

  it('an unknown bracket id never silently matches everything', () => {
    expect(matchesBrackets(band(50_000, 60_000), ['not-a-bracket'])).toBe(false);
  });

  it('the brackets tile the range with no gap between them', () => {
    // A gap would make a salary unreachable by any bracket — e.g. a £40,001 role invisible
    // to both "£30–40k" and "£40–50k".
    for (let i = 1; i < SALARY_BRACKETS.length; i += 1) {
      expect(SALARY_BRACKETS[i]!.minK).toBe(SALARY_BRACKETS[i - 1]!.maxK);
    }
  });
});

describe('custom salary window', () => {
  const band = (min: number | null, max: number | null) =>
    salaryBand(job({ salary_min: min, salary_max: max }));

  it('an empty window is no restriction', () => {
    expect(matchesCustomRange(band(20_000, 25_000), null, null)).toBe(true);
  });

  it('a floor alone excludes anything entirely beneath it', () => {
    expect(matchesCustomRange(band(30_000, 40_000), 60, null)).toBe(false);
    expect(matchesCustomRange(band(55_000, 70_000), 60, null)).toBe(true);
  });

  it('a ceiling alone excludes anything entirely above it', () => {
    expect(matchesCustomRange(band(90_000, 110_000), null, 70)).toBe(false);
  });

  it('a one-sided band is compared on the figure it does have', () => {
    // "Up to £60,000" publishes a ceiling and no floor. Treating the missing floor as zero
    // would put it below every minimum the operator could set.
    expect(matchesCustomRange(band(null, 60_000), 50, null)).toBe(true);
  });
});

describe('overlapsWindow', () => {
  it('an unpublished band never matches a window', () => {
    expect(overlapsWindow(salaryBand(job()), 0, null)).toBe(false);
  });
});

describe('formatSalary', () => {
  it('formats a range in the posting’s own currency', () => {
    expect(formatSalary(salaryBand(job({ salary_min: 90_000, salary_max: 110_000, salary_currency: 'GBP' }))))
      .toBe('£90k–£110k');
    expect(formatSalary(salaryBand(job({ salary_min: 120_000, salary_max: 150_000, salary_currency: 'USD' }))))
      .toBe('$120k–$150k');
  });

  it('says which end of the band is the one the posting gave', () => {
    expect(formatSalary(salaryBand(job({ salary_max: 60_000 })))).toBe('Up to £60k');
    expect(formatSalary(salaryBand(job({ salary_min: 70_000 })))).toBe('From £70k');
  });

  it('collapses a single figure rather than printing it twice', () => {
    expect(formatSalary(salaryBand(job({ salary_min: 72_000, salary_max: 72_000 })))).toBe('£72k');
  });

  it('returns nothing for an unpublished salary so the caller can say so in words', () => {
    expect(formatSalary(salaryBand(job()))).toBeNull();
  });
});
