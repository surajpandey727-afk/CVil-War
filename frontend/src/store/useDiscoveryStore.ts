import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import { DEFAULT_ACTIVE_TITLES, type RoleFamily } from '@/lib/roleTargets';

export type SortKey = 'match' | 'newest' | 'salary';
export type PostedWithin = '24h' | '7d' | '30d' | 'any';

export interface DiscoveryFilters {
  /** 0–100. Roles below this are still listed but never auto-applied to. */
  minAtsScore: number;
  /** Thousands of GBP. 0 disables the filter. */
  minSalaryK: number;
  seniority: string[];
  postedWithin: PostedWithin;
  remoteOnly: boolean;
  hideApplied: boolean;
  publishedSalaryOnly: boolean;
  sort: SortKey;
}

export const DEFAULT_FILTERS: DiscoveryFilters = {
  minAtsScore: 70,
  minSalaryK: 0,
  seniority: [],
  postedWithin: '30d',
  remoteOnly: false,
  hideApplied: true,
  publishedSalaryOnly: false,
  sort: 'match',
};

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
}

const without = <T,>(arr: T[], v: T): T[] => arr.filter((x) => x !== v);
const toggle = <T,>(arr: T[], v: T): T[] => (arr.includes(v) ? without(arr, v) : [...arr, v]);

/**
 * Discovery preferences: role targets, source selection and filters.
 *
 * Persisted, because these are a standing profile rather than per-visit state — the operator
 * configures them once and every subsequent search, alert and auto-apply decision reads them.
 * `selectedJobIds` is deliberately excluded from persistence: resuming a page with jobs
 * silently ticked is how you start a run you did not intend.
 */
export const useDiscoveryStore = create<DiscoveryState>()(
  persist(
    (set) => ({
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
    }),
    {
      name: 'cvil-war-discovery',
      // v2 clears a selection seeded from the stale static catalogue. Anyone who had it
      // persisted was silently missing every career-page job — 28 of 55 London roles in the
      // reference cache — with no way to tell from the screen.
      version: 2,
      migrate: (persisted: unknown, from: number) => {
        const state = (persisted ?? {}) as Record<string, unknown>;
        if (from < 2) state['enabledSources'] = [];
        return state;
      },
      partialize: (s) => ({
        activeTitles: s.activeTitles,
        activeFamilies: s.activeFamilies,
        enabledSources: s.enabledSources,
        filters: s.filters,
        location: s.location,
        query: s.query,
        appliedLocation: s.appliedLocation,
        appliedQuery: s.appliedQuery,
      }),
    },
  ),
);
