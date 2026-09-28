import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import { DEFAULT_ACTIVE_TITLES, type RoleFamily } from '@/lib/roleTargets';
import type { SponsorshipStatus } from '@/types/job';

export type SortKey = 'match' | 'newest' | 'salary';
export type PostedWithin = '24h' | '7d' | '30d' | 'any';

export interface DiscoveryFilters {
  /** 0–100. Roles below this are still listed but never auto-applied to. */
  minAtsScore: number;
  /** Selected ids from `SALARY_BRACKETS`. Empty means no bracket restriction. */
  salaryBrackets: string[];
  /** Custom window in thousands, applied on top of the brackets. `null` means unbounded. */
  salaryCustomMinK: number | null;
  salaryCustomMaxK: number | null;
  /**
   * Which sponsorship answers to show. Empty means all three.
   *
   * `not_specified` is a first-class option rather than being folded into either of the
   * others: most postings never mention sponsorship, so a two-way "sponsors / does not"
   * filter would either hide most of the market or claim an answer no posting gave.
   */
  sponsorship: SponsorshipStatus[];
  seniority: string[];
  postedWithin: PostedWithin;
  remoteOnly: boolean;
  hideApplied: boolean;
  publishedSalaryOnly: boolean;
  sort: SortKey;
}

export const DEFAULT_FILTERS: DiscoveryFilters = {
  minAtsScore: 70,
  salaryBrackets: [],
  salaryCustomMinK: null,
  salaryCustomMaxK: null,
  sponsorship: [],
  seniority: [],
  postedWithin: '30d',
  remoteOnly: false,
  hideApplied: true,
  publishedSalaryOnly: false,
  sort: 'match',
};

/** One search the operator actually ran, kept so they can run it again.
 *
 *  The whole search is stored, not just the words: a query means something different against
 *  a different location, a different set of sources and a different salary window, and
 *  restoring only the text would silently re-run it under whatever filters happen to be set
 *  now. Re-running a recent search restores the conditions it was run under.
 */
export interface RecentSearch {
  /** Signature of the search itself — repeating a search updates its entry, never adds one. */
  id: string;
  query: string;
  location: string;
  /** Source keys the fan-out actually used, not the operator's selection. */
  sources: string[];
  filters: DiscoveryFilters;
  /** Epoch milliseconds. */
  at: number;
  /** What the search returned, once it has. `null` while it is still running. */
  resultCount: number | null;
}

/** Enough entries to cover a session's worth of exploring, few enough to scan at a glance. */
const MAX_RECENT = 10;

/** What makes two searches "the same search" for dedupe purposes. */
function signature(entry: Omit<RecentSearch, 'id' | 'at' | 'resultCount'>): string {
  const { query, location, sources, filters } = entry;
  return [
    query.trim().toLowerCase(),
    location.trim().toLowerCase(),
    [...sources].sort().join(','),
    [...filters.salaryBrackets].sort().join(','),
    filters.salaryCustomMinK ?? '',
    filters.salaryCustomMaxK ?? '',
    [...filters.sponsorship].sort().join(','),
  ].join('|');
}

interface DiscoveryState {
  /** Active role-target titles. Drives the search query and the résumé rules. */
  activeTitles: string[];
  /** Role families used as quick filter chips on the Jobs screen. */
  activeFamilies: RoleFamily[];
  /** Enabled source keys. Anything not listed is excluded from search. */
  enabledSources: string[];
  filters: DiscoveryFilters;
  /** Job ids ticked for the next run. Not persisted — a run is a session-level action. */
  selectedJobIds: string[];
  location: string;
  query: string;
  /** Searches the operator has run, most recent first. */
  recentSearches: RecentSearch[];
  /**
   * The location/title the *listed results* are filtered by, as opposed to what is currently
   * typed in the boxes. Kept separate so the server is not re-queried on every keystroke and
   * so the visible list always corresponds to a search the operator actually ran.
   */
  appliedLocation: string;
  appliedQuery: string;

  setQuery: (v: string) => void;
  setLocation: (v: string) => void;
  /** Promote the typed location/title to the filter the list is fetched with. */
  commitSearch: () => void;
  toggleTitle: (title: string) => void;
  setTitles: (titles: string[]) => void;
  toggleFamily: (family: RoleFamily) => void;
  toggleSource: (key: string) => void;
  setSources: (keys: string[]) => void;
  patchFilters: (patch: Partial<DiscoveryFilters>) => void;
  resetFilters: () => void;
  toggleJob: (id: string) => void;
  setSelected: (ids: string[]) => void;
  clearSelection: () => void;

  /** Record a search that was just run. Returns the entry's id so the count can be filled in. */
  recordSearch: (entry: Omit<RecentSearch, 'id' | 'at' | 'resultCount'>) => string;
  /** Attach the result count once the search comes back. */
  setRecentResultCount: (id: string, count: number) => void;
  /** Put a recent search's conditions back in place, ready to re-run. */
  restoreSearch: (id: string) => RecentSearch | undefined;
  removeRecentSearch: (id: string) => void;
  clearRecentSearches: () => void;
}

/**
 * Bring persisted preferences forward. Exported so it can be tested directly — a migration
 * only ever runs once per browser, on data written by a version that no longer exists, which
 * makes it the hardest thing in the store to find a bug in after the fact.
 *
 * v2 cleared a selection seeded from the stale static catalogue. Anyone who had it persisted
 * was silently missing every career-page job — 28 of 55 London roles in the reference cache —
 * with no way to tell from the screen.
 *
 * v3 replaces the single `minSalaryK` slider with brackets plus a custom window, and adds the
 * sponsorship filter.
 */
export function migrateDiscoveryState(persisted: unknown, from: number): Record<string, unknown> {
  const state = (persisted ?? {}) as Record<string, unknown>;
  if (from < 2) state['enabledSources'] = [];
  if (from < 3) {
    const filters = { ...((state['filters'] ?? {}) as Record<string, unknown>) };
    const legacyMin = filters['minSalaryK'];
    delete filters['minSalaryK'];
    state['filters'] = {
      ...DEFAULT_FILTERS,
      ...filters,
      // A slider sitting at 0 meant "no filter", not "£0 and above". Carrying the zero over
      // as a floor would have turned everyone's untouched slider into an active filter.
      salaryCustomMinK: typeof legacyMin === 'number' && legacyMin > 0 ? legacyMin : null,
    };
  }
  return state;
}

const without = <T,>(arr: T[], v: T): T[] => arr.filter((x) => x !== v);
const toggle = <T,>(arr: T[], v: T): T[] => (arr.includes(v) ? without(arr, v) : [...arr, v]);

/**
 * Discovery preferences: role targets, source selection, filters and search history.
 *
 * Persisted, because these are a standing profile rather than per-visit state — the operator
 * configures them once and every subsequent search, alert and auto-apply decision reads them.
 * `selectedJobIds` is deliberately excluded from persistence: resuming a page with jobs
 * silently ticked is how you start a run you did not intend.
 */
export const useDiscoveryStore = create<DiscoveryState>()(
  persist(
    (set, get) => ({
      activeTitles: DEFAULT_ACTIVE_TITLES,
      activeFamilies: [],
      // Empty means "every source the registry reports". Seeding from the static catalogue
      // is what hid the career-page sources: that file marks every `careers:*` entry
      // not_implemented, which was false for nine of them.
      enabledSources: [],
      filters: DEFAULT_FILTERS,
      selectedJobIds: [],
      location: 'London, UK',
      query: '',
      recentSearches: [],
      appliedLocation: 'London, UK',
      appliedQuery: '',

      setQuery: (v) => set({ query: v }),
      setLocation: (v) => set({ location: v }),
      commitSearch: () => set((s) => ({ appliedLocation: s.location, appliedQuery: s.query })),
      toggleTitle: (title) => set((s) => ({ activeTitles: toggle(s.activeTitles, title) })),
      setTitles: (titles) => set({ activeTitles: titles }),
      toggleFamily: (family) => set((s) => ({ activeFamilies: toggle(s.activeFamilies, family) })),
      toggleSource: (key) => set((s) => ({ enabledSources: toggle(s.enabledSources, key) })),
      setSources: (keys) => set({ enabledSources: keys }),
      patchFilters: (patch) => set((s) => ({ filters: { ...s.filters, ...patch } })),
      resetFilters: () => set({ filters: DEFAULT_FILTERS, activeFamilies: [] }),
      toggleJob: (id) => set((s) => ({ selectedJobIds: toggle(s.selectedJobIds, id) })),
      setSelected: (ids) => set({ selectedJobIds: ids }),
      clearSelection: () => set({ selectedJobIds: [] }),

      recordSearch: (entry) => {
        const id = signature(entry);
        set((s) => ({
          // Move-to-top on a repeat rather than appending a duplicate: running the same
          // search twice is the normal way to check for new postings, and a history that
          // fills up with ten copies of it is no history at all.
          recentSearches: [
            { ...entry, id, at: Date.now(), resultCount: null },
            ...s.recentSearches.filter((r) => r.id !== id),
          ].slice(0, MAX_RECENT),
        }));
        return id;
      },
      setRecentResultCount: (id, count) =>
        set((s) => ({
          recentSearches: s.recentSearches.map((r) =>
            r.id === id ? { ...r, resultCount: count } : r,
          ),
        })),
      restoreSearch: (id) => {
        const entry = get().recentSearches.find((r) => r.id === id);
        if (!entry) return undefined;
        set({
          query: entry.query,
          location: entry.location,
          filters: entry.filters,
          enabledSources: entry.sources,
        });
        return entry;
      },
      removeRecentSearch: (id) =>
        set((s) => ({ recentSearches: s.recentSearches.filter((r) => r.id !== id) })),
      clearRecentSearches: () => set({ recentSearches: [] }),
    }),
    {
      name: 'cvil-war-discovery',
      // v2 cleared a selection seeded from the stale static catalogue. Anyone who had it
      // persisted was silently missing every career-page job — 28 of 55 London roles in the
      // reference cache — with no way to tell from the screen.
      // v3 replaces the single `minSalaryK` slider with brackets plus a custom window, and
      // adds the sponsorship filter.
      version: 3,
      migrate: migrateDiscoveryState,
      partialize: (s) => ({
        activeTitles: s.activeTitles,
        activeFamilies: s.activeFamilies,
        enabledSources: s.enabledSources,
        filters: s.filters,
        location: s.location,
        query: s.query,
        recentSearches: s.recentSearches,
        appliedLocation: s.appliedLocation,
        appliedQuery: s.appliedQuery,
      }),
    },
  ),
);
