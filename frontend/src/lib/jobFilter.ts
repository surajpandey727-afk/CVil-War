/** The operator's standing preferences, applied to the stored corpus.
 *
 *  Lives outside the Jobs page so it can be exercised directly: the filter is what decides
 *  whether a role the candidate wanted ever reaches the screen, and testing it only through a
 *  rendered page means every case costs a full mount and a network round trip — which is how
 *  it ended up with one broken rule per filter and no test that noticed.
 *
 *  Alongside the surviving jobs it counts *which* control rejected each one. An empty screen
 *  saying "23 roles were filtered out", leaving the operator to guess which of ten controls
 *  did it, is barely better than showing nothing: the real question is "what is hiding my
 *  jobs, and how do I undo it". Each job is charged to the first filter that rejects it, so
 *  the counts sum to the number hidden rather than double-counting.
 */

import { atsPercent } from '@/lib/status';
import { familyForTitle, type RoleFamily } from '@/lib/roleTargets';
import { matchesBrackets, matchesCustomRange, salaryBand, sponsorshipStatus } from '@/lib/jobModel';
import type { DiscoveryFilters } from '@/store/useDiscoveryStore';
import type { Job } from '@/types/job';

export const POSTED_WINDOWS: { key: DiscoveryFilters['postedWithin']; label: string; days: number }[] = [
  { key: '24h', label: '24h', days: 1 },
  { key: '7d', label: '7d', days: 7 },
  { key: '30d', label: '30d', days: 30 },
  { key: 'any', label: 'Any', days: 3650 },
];

/** Days since a posting went up. A missing date is unknown, not old — see `applyJobFilters`. */
export function ageInDays(iso: string | null): number {
  if (!iso) return 9999;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 9999;
  return (Date.now() - t) / 86_400_000;
}

/** What to sort a job by when sorting on pay: its floor, or its ceiling when it published
 *  only one. Unpublished sorts last rather than as zero — it is unknown, not badly paid. */
export function sortableSalary(job: Job): number {
  const band = salaryBand(job);
  return band.min ?? band.max ?? -1;
}

export interface FilterContext {
  filters: DiscoveryFilters;
  activeFamilies: RoleFamily[];
  /** The operator's source selection. Empty means "every source", not "none". */
  enabledSources: string[];
  /** Keys the live registry reports. A source it has never heard of is never dropped. */
  knownKeys: Set<string>;
}

export interface FilterResult {
  jobs: Job[];
  /** Filter key to the number of roles it removed. Keys match `FilterCulprits`' labels. */
  rejected: Record<string, number>;
}

export function applyJobFilters(allJobs: Job[], ctx: FilterContext): FilterResult {
  const { filters, activeFamilies, enabledSources, knownKeys } = ctx;
  const maxAge = POSTED_WINDOWS.find((p) => p.key === filters.postedWithin)?.days ?? 3650;
  // An empty selection means "no restriction", not "exclude everything" — the operator has
  // simply never narrowed the list.
  const restrictSources = enabledSources.length > 0;
  const enabled = new Set(enabledSources);
  const sponsorshipWanted = new Set(filters.sponsorship);
  const seniorityWanted = filters.seniority.map((s) => s.toLowerCase());

  const rejected: Record<string, number> = {};
  const reject = (key: string) => {
    rejected[key] = (rejected[key] ?? 0) + 1;
    return false;
  };

  const out = allJobs.filter((j) => {
    // Only exclude a source the operator has actually switched off. A job whose source the
    // registry does not recognise must never be dropped silently: the static catalogue in
    // lib/sources marks every `careers:*` entry not_implemented, which was false for nine of
    // them and hid 28 of 55 London jobs. The live registry decides what exists; this filter
    // only applies the operator's own choices on top of it.
    if (restrictSources && knownKeys.has(j.platform) && !enabled.has(j.platform)) {
      return reject('sources');
    }
    if (atsPercent(j.match_score) < filters.minAtsScore && j.match_score != null) {
      return reject('minAtsScore');
    }
    if (filters.remoteOnly && !j.remote) return reject('remoteOnly');
    // Was `status !== 'new' && status !== 'discovered'`, which also caught 'saved' — a
    // genuinely distinct, still-relevant status. That meant saving a job for later
    // immediately hid it from the default view (hideApplied is on by default), the opposite
    // of what "save for later" is for. Only an actual 'applied' status is what this filter's
    // own label promises to hide.
    if (filters.hideApplied && j.status === 'applied') return reject('hideApplied');
    // A missing posted_date is unknown, not old: excluding it would silently drop every
    // source that does not publish one (Arbeitnow, several career pages).
    if (j.posted_date && ageInDays(j.posted_date) > maxAge) return reject('postedWithin');

    // Salary and sponsorship read the canonical fields the server derived, the same ones the
    // card renders. When each parsed `salary_range` for itself they disagreed, and a card
    // showing "£60,000" was removed by a £50k minimum that had read the "+ 10% bonus" in the
    // same string as £10,000.
    const band = salaryBand(j);
    if (filters.publishedSalaryOnly && !band.published) return reject('publishedSalaryOnly');
    // A posting with no published band is never excluded by a salary window. Most UK
    // postings publish nothing, so treating them as £0 would hide the majority of the market
    // behind a filter the operator only meant to narrow it with.
    if (band.published) {
      if (!matchesBrackets(band, filters.salaryBrackets)) return reject('salaryBrackets');
      if (!matchesCustomRange(band, filters.salaryCustomMinK, filters.salaryCustomMaxK)) {
        return reject('salaryCustom');
      }
    }

    if (sponsorshipWanted.size && !sponsorshipWanted.has(sponsorshipStatus(j))) {
      return reject('sponsorship');
    }

    if (seniorityWanted.length) {
      const level = (j.experience_level ?? '').toLowerCase();
      if (!seniorityWanted.some((s) => level.includes(s))) return reject('seniority');
    }
    if (activeFamilies.length && !activeFamilies.includes(familyForTitle(j.title))) {
      return reject('roleTargets');
    }
    return true;
  });

  out.sort((a, b) => {
    if (filters.sort === 'match') return atsPercent(b.match_score) - atsPercent(a.match_score);
    if (filters.sort === 'newest') return ageInDays(a.posted_date) - ageInDays(b.posted_date);
    return sortableSalary(b) - sortableSalary(a);
  });

  return { jobs: out, rejected };
}
