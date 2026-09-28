/** The filter pass, exercised directly rather than through a rendered page.
 *
 *  Every rule here decides whether a role the candidate wanted ever reaches the screen, and a
 *  rule that is wrong fails silently — the list is simply shorter. Testing them only through
 *  the page cost a full mount and a network round trip per case, which is why several of them
 *  had no test at all.
 */
import { describe, it, expect } from 'vitest';

import { applyJobFilters, ageInDays, sortableSalary } from '@/lib/jobFilter';
import { DEFAULT_FILTERS, type DiscoveryFilters } from '@/store/useDiscoveryStore';
import type { Job } from '@/types/job';

let seq = 0;
function job(overrides: Partial<Job> = {}): Job {
  seq += 1;
  return {
    id: `j${seq}`, platform: 'remotive', platform_job_id: `p${seq}`, title: 'ML Engineer',
    company: 'Northwind', location: 'London', url: 'https://x', description: '',
    salary_range: null, job_type: null, remote: true, posted_date: null,
    experience_level: 'Senior', match_score: 0.9, skills_required: null, status: 'new',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    sponsor_confidence: 'unknown', sponsor_evidence: null, sponsorship_status: 'not_specified',
    ...overrides,
  } as Job;
}

const ctx = (filters: Partial<DiscoveryFilters> = {}, extra: Partial<{
  enabledSources: string[]; knownKeys: Set<string>; activeFamilies: never[];
}> = {}) => ({
  filters: { ...DEFAULT_FILTERS, ...filters },
  activeFamilies: [],
  enabledSources: [],
  knownKeys: new Set(['remotive', 'adzuna']),
  ...extra,
});

describe('source selection', () => {
  it('an empty selection means every source, not none', () => {
    const { jobs } = applyJobFilters([job(), job({ platform: 'adzuna' })], ctx());
    expect(jobs).toHaveLength(2);
  });

  it('excludes only the sources actually switched off', () => {
    const { jobs, rejected } = applyJobFilters(
      [job({ platform: 'remotive' }), job({ platform: 'adzuna' })],
      ctx({}, { enabledSources: ['adzuna'] }),
    );
    expect(jobs.map((j) => j.platform)).toEqual(['adzuna']);
    expect(rejected['sources']).toBe(1);
  });

  it('never drops a job from a source the registry has not heard of', () => {
    // The static catalogue marked every `careers:*` entry not_implemented, which was false
    // for nine of them and hid 28 of 55 London jobs behind an empty screen.
    const { jobs } = applyJobFilters(
      [job({ platform: 'careers:wise' })],
      ctx({}, { enabledSources: ['adzuna'] }),
    );
    expect(jobs).toHaveLength(1);
  });
});

describe('posted-within', () => {
  const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString();

  it('removes anything older than the window', () => {
    const { jobs, rejected } = applyJobFilters(
      [job({ posted_date: daysAgo(2) }), job({ posted_date: daysAgo(40) })],
      ctx({ postedWithin: '7d' }),
    );
    expect(jobs).toHaveLength(1);
    expect(rejected['postedWithin']).toBe(1);
  });

  it('a missing date is unknown, not old', () => {
    // Excluding it would silently drop every source that does not publish one — Arbeitnow
    // and several career pages among them.
    const { jobs } = applyJobFilters([job({ posted_date: null })], ctx({ postedWithin: '24h' }));
    expect(jobs).toHaveLength(1);
  });

  it('an unparseable date is treated as unknown rather than crashing', () => {
    expect(ageInDays('not-a-date')).toBe(9999);
  });
});

describe('hide already applied', () => {
  it('hides an applied role', () => {
    const { jobs } = applyJobFilters([job({ status: 'applied' })], ctx({ hideApplied: true }));
    expect(jobs).toHaveLength(0);
  });

  it('a saved role stays visible', () => {
    // "Save for later" that immediately hides the job is the opposite of what it is for.
    const { jobs } = applyJobFilters([job({ status: 'saved' })], ctx({ hideApplied: true }));
    expect(jobs).toHaveLength(1);
  });
});

describe('ATS threshold', () => {
  it('removes a role below the floor', () => {
    const { jobs } = applyJobFilters([job({ match_score: 0.4 })], ctx({ minAtsScore: 70 }));
    expect(jobs).toHaveLength(0);
  });

  it('a role with no score yet is not treated as a zero score', () => {
    // It has not been scored, which is not the same as scoring badly.
    const { jobs } = applyJobFilters([job({ match_score: null })], ctx({ minAtsScore: 70 }));
    expect(jobs).toHaveLength(1);
  });
});

describe('charging each hidden role to one filter', () => {
  it('counts sum to the number hidden rather than double-counting', () => {
    const jobs = [
      job({ remote: false, match_score: 0.2 }),
      job({ remote: false, match_score: 0.2 }),
      job({ status: 'applied' }),
    ];
    const result = applyJobFilters(jobs, ctx({ remoteOnly: true, minAtsScore: 70 }));
    const hidden = jobs.length - result.jobs.length;
    const charged = Object.values(result.rejected).reduce((a, b) => a + b, 0);
    expect(charged).toBe(hidden);
  });
});

describe('sorting', () => {
  it('sorts by pay on the canonical band, not on whichever number came first', () => {
    const low = job({ title: 'Low', salary_range: 'Up to £60,000 + 10% bonus', salary_max: 60_000 });
    const high = job({ title: 'High', salary_range: '£500 per day', salary_min: 110_000, salary_annualised: true });
    const { jobs } = applyJobFilters([low, high], ctx({ sort: 'salary' }));
    expect(jobs.map((j) => j.title)).toEqual(['High', 'Low']);
  });

  it('a role with no published salary sorts last rather than as zero-paid', () => {
    expect(sortableSalary(job())).toBe(-1);
  });

  it('sorts newest first on the posted date', () => {
    const older = job({ title: 'Older', posted_date: '2026-01-01T00:00:00Z' });
    const newer = job({ title: 'Newer', posted_date: '2026-06-01T00:00:00Z' });
    // `postedWithin: 'any'` because the default 30-day window would remove both fixtures and
    // leave the sort assertion comparing two empty lists.
    const { jobs } = applyJobFilters([older, newer], ctx({ sort: 'newest', postedWithin: 'any' }));
    expect(jobs.map((j) => j.title)).toEqual(['Newer', 'Older']);
  });
});

describe('the filter pass stays fast enough to run on every keystroke', () => {
  // It runs inside a useMemo on the render path, so a slow pass shows up as a filter panel
  // that lags behind the control the operator is dragging. The list endpoint caps at 100
  // jobs today; 5,000 gives a wide margin over any realistic growth in that cap.
  it('handles a corpus far larger than the page ever fetches, well inside a frame budget', () => {
    const corpus = Array.from({ length: 5_000 }, (_, i) =>
      job({
        platform: i % 2 ? 'remotive' : 'adzuna',
        match_score: (i % 100) / 100,
        salary_min: 30_000 + (i % 70) * 1_000,
        salary_max: 45_000 + (i % 70) * 1_000,
        posted_date: new Date(Date.now() - (i % 60) * 86_400_000).toISOString(),
        sponsorship_status: (['available', 'not_specified', 'none'] as const)[i % 3],
      }),
    );

    const started = performance.now();
    const { jobs } = applyJobFilters(
      corpus,
      ctx({
        minAtsScore: 40,
        salaryBrackets: ['50-60', '60-75'],
        sponsorship: ['available', 'not_specified'],
        sort: 'salary',
      }),
    );
    const elapsed = performance.now() - started;

    expect(jobs.length).toBeGreaterThan(0);
    // Two frames at 60fps. Generous on purpose: this is a guard against an accidentally
    // quadratic rule (an `includes` over an array inside the predicate, say), not a
    // benchmark, and a tight bound would just make it flaky on a loaded CI box.
    expect(elapsed).toBeLessThan(33);
  });

  it('does not degrade when the operator has narrowed to many sources', () => {
    // `enabledSources.includes(...)` inside the predicate made this O(jobs × sources). With
    // the full career-page catalogue selected that is 5,000 × 70 string comparisons per
    // render.
    const enabledSources = Array.from({ length: 200 }, (_, i) => `careers:employer${i}`);
    const knownKeys = new Set(enabledSources);
    const corpus = Array.from({ length: 5_000 }, (_, i) =>
      job({ platform: `careers:employer${i % 200}` }),
    );

    const started = performance.now();
    const { jobs } = applyJobFilters(corpus, { ...ctx(), enabledSources, knownKeys });
    const elapsed = performance.now() - started;

    expect(jobs).toHaveLength(5_000);
    expect(elapsed).toBeLessThan(33);
  });
});
