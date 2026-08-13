import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import { DEFAULT_ACTIVE_TITLES, type RoleFamily } from '@/lib/roleTargets';
import { WORKING_SOURCE_KEYS } from '@/lib/sources';

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

  setQuery: (v: string) => void;
  setLocation: (v: string) => void;
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
      enabledSources: WORKING_SOURCE_KEYS,
      filters: DEFAULT_FILTERS,
      selectedJobIds: [],
      location: 'London, UK',
      query: '',

      setQuery: (v) => set({ query: v }),
      setLocation: (v) => set({ location: v }),
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
      partialize: (s) => ({
        activeTitles: s.activeTitles,
        activeFamilies: s.activeFamilies,
        enabledSources: s.enabledSources,
        filters: s.filters,
        location: s.location,
        query: s.query,
      }),
    },
  ),
);
