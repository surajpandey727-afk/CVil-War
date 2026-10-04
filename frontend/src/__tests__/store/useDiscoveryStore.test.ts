/** Search history and the filter migration.
 *
 *  Both are persisted state, which is the kind that fails quietly: a bug here shows up as a
 *  history that fills with duplicates, or as everyone's saved salary filter changing meaning
 *  on the release that shipped the new one.
 */
import { describe, it, expect, beforeEach } from 'vitest';

import {
  useDiscoveryStore, DEFAULT_FILTERS, migrateDiscoveryState, type DiscoveryFilters,
} from '@/store/useDiscoveryStore';

const filters = (patch: Partial<DiscoveryFilters> = {}): DiscoveryFilters => ({
  ...DEFAULT_FILTERS,
  ...patch,
});

describe('recent searches', () => {
  beforeEach(() => {
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({ recentSearches: [], filters: DEFAULT_FILTERS });
  });

  it('records a search with the conditions it ran under', () => {
    const { recordSearch } = useDiscoveryStore.getState();
    recordSearch({
      query: 'ML Engineer',
      location: 'London, UK',
      sources: ['remotive', 'adzuna'],
      filters: filters({ salaryBrackets: ['60-75'] }),
    });

    const [entry] = useDiscoveryStore.getState().recentSearches;
    expect(entry).toBeDefined();
    expect(entry!.query).toBe('ML Engineer');
    expect(entry!.location).toBe('London, UK');
    expect(entry!.sources).toEqual(['remotive', 'adzuna']);
    expect(entry!.filters.salaryBrackets).toEqual(['60-75']);
    // Not zero — the count is unknown until the search comes back, and a search still
    // running is not a search that found nothing.
    expect(entry!.resultCount).toBeNull();
  });

  it('newest first', () => {
    const { recordSearch } = useDiscoveryStore.getState();
    recordSearch({ query: 'first', location: '', sources: [], filters: filters() });
    recordSearch({ query: 'second', location: '', sources: [], filters: filters() });

    expect(useDiscoveryStore.getState().recentSearches.map((r) => r.query))
      .toEqual(['second', 'first']);
  });

  it('repeating a search moves it to the top rather than adding a copy', () => {
    // Re-running a search to check for new postings is the normal way to use this. A history
    // that fills with ten copies of it is not a history.
    const { recordSearch } = useDiscoveryStore.getState();
    recordSearch({ query: 'ML Engineer', location: 'London', sources: ['reed'], filters: filters() });
    recordSearch({ query: 'Data Scientist', location: 'London', sources: ['reed'], filters: filters() });
    recordSearch({ query: 'ML Engineer', location: 'London', sources: ['reed'], filters: filters() });

    const history = useDiscoveryStore.getState().recentSearches;
    expect(history).toHaveLength(2);
    expect(history[0]!.query).toBe('ML Engineer');
  });

  it('the same words against a different location are two different searches', () => {
    const { recordSearch } = useDiscoveryStore.getState();
    recordSearch({ query: 'ML Engineer', location: 'London', sources: [], filters: filters() });
    recordSearch({ query: 'ML Engineer', location: 'Manchester', sources: [], filters: filters() });

    expect(useDiscoveryStore.getState().recentSearches).toHaveLength(2);
  });

  it('the same words under a different salary bracket are two different searches', () => {
    const { recordSearch } = useDiscoveryStore.getState();
    recordSearch({ query: 'ML Engineer', location: '', sources: [], filters: filters() });
    recordSearch({
      query: 'ML Engineer', location: '', sources: [],
      filters: filters({ salaryBrackets: ['75+'] }),
    });

    expect(useDiscoveryStore.getState().recentSearches).toHaveLength(2);
  });

  it('caps the history rather than growing without bound', () => {
    const { recordSearch } = useDiscoveryStore.getState();
    for (let i = 0; i < 25; i += 1) {
      recordSearch({ query: `search ${i}`, location: '', sources: [], filters: filters() });
    }
    const history = useDiscoveryStore.getState().recentSearches;
    expect(history).toHaveLength(10);
    expect(history[0]!.query).toBe('search 24');
  });

  it('fills in the result count once the search returns', () => {
    const { recordSearch, setRecentResultCount } = useDiscoveryStore.getState();
    const id = recordSearch({ query: 'ML', location: '', sources: [], filters: filters() });
    setRecentResultCount(id, 42);

    expect(useDiscoveryStore.getState().recentSearches[0]!.resultCount).toBe(42);
  });

  it('restoring puts the whole search back, not just its words', () => {
    // Restoring only the text would re-run the search under whatever filters happen to be
    // set now, which is a different search wearing the same name.
    const { recordSearch, restoreSearch, patchFilters } = useDiscoveryStore.getState();
    const id = recordSearch({
      query: 'Applied Scientist',
      location: 'Cambridge',
      sources: ['reed', 'adzuna'],
      filters: filters({ salaryBrackets: ['75+'], sponsorship: ['available'] }),
    });

    patchFilters({ salaryBrackets: [], sponsorship: [], remoteOnly: true });
    const restored = restoreSearch(id);

    const state = useDiscoveryStore.getState();
    expect(restored?.query).toBe('Applied Scientist');
    expect(state.query).toBe('Applied Scientist');
    expect(state.location).toBe('Cambridge');
    expect(state.enabledSources).toEqual(['reed', 'adzuna']);
    expect(state.filters.salaryBrackets).toEqual(['75+']);
    expect(state.filters.sponsorship).toEqual(['available']);
    expect(state.filters.remoteOnly).toBe(false);
  });

  it('restoring an entry that is no longer there changes nothing', () => {
    const { restoreSearch } = useDiscoveryStore.getState();
    useDiscoveryStore.setState({ query: 'untouched' });
    expect(restoreSearch('gone')).toBeUndefined();
    expect(useDiscoveryStore.getState().query).toBe('untouched');
  });

  it('removes one entry without disturbing the others', () => {
    const { recordSearch, removeRecentSearch } = useDiscoveryStore.getState();
    const first = recordSearch({ query: 'a', location: '', sources: [], filters: filters() });
    recordSearch({ query: 'b', location: '', sources: [], filters: filters() });
    removeRecentSearch(first);

    expect(useDiscoveryStore.getState().recentSearches.map((r) => r.query)).toEqual(['b']);
  });

  it('clears the whole history', () => {
    const { recordSearch, clearRecentSearches } = useDiscoveryStore.getState();
    recordSearch({ query: 'a', location: '', sources: [], filters: filters() });
    clearRecentSearches();
    expect(useDiscoveryStore.getState().recentSearches).toEqual([]);
  });
});

describe('migrating preferences saved by an earlier version', () => {
  it('an untouched £0 slider does not become an active £0 floor', () => {
    const migrated = migrateDiscoveryState(
      { filters: { ...DEFAULT_FILTERS, minSalaryK: 0 } },
      2,
    ) as { filters: DiscoveryFilters };

    expect(migrated.filters.salaryCustomMinK).toBeNull();
  });

  it('a slider the operator had actually set is carried over as the custom floor', () => {
    const migrated = migrateDiscoveryState(
      { filters: { ...DEFAULT_FILTERS, minSalaryK: 65 } },
      2,
    ) as { filters: DiscoveryFilters };

    expect(migrated.filters.salaryCustomMinK).toBe(65);
  });

  it('the retired field is not left behind on the saved state', () => {
    const migrated = migrateDiscoveryState({ filters: { minSalaryK: 40 } }, 2) as {
      filters: Record<string, unknown>;
    };
    expect(migrated.filters).not.toHaveProperty('minSalaryK');
  });

  it('the new filters arrive at their defaults rather than undefined', () => {
    // An undefined `sponsorship` would crash the filter pass on `.includes`, and an undefined
    // `salaryBrackets` would do the same — on the first render after upgrading, for everyone
    // who had ever saved a preference.
    const migrated = migrateDiscoveryState({ filters: { minAtsScore: 80 } }, 1) as {
      filters: DiscoveryFilters;
    };
    expect(migrated.filters.sponsorship).toEqual([]);
    expect(migrated.filters.salaryBrackets).toEqual([]);
    expect(migrated.filters.salaryCustomMaxK).toBeNull();
    expect(migrated.filters.minAtsScore).toBe(80);
  });

  it('survives state with no filters at all', () => {
    const migrated = migrateDiscoveryState({}, 1) as { filters: DiscoveryFilters };
    expect(migrated.filters).toEqual({ ...DEFAULT_FILTERS, salaryCustomMinK: null });
  });

  it('survives null persisted state', () => {
    expect(() => migrateDiscoveryState(null, 1)).not.toThrow();
  });
});

describe('persisted state survives a reload', () => {
  it('writes the history to storage under the store key', () => {
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({ recentSearches: [] });
    useDiscoveryStore.getState().recordSearch({
      query: 'Persisted search', location: 'London', sources: ['reed'], filters: filters(),
    });

    const raw = localStorage.getItem('cvil-war-discovery');
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).state.recentSearches[0].query).toBe('Persisted search');
  });
});

describe('migrateDiscoveryState: the retired 70% match floor (v4)', () => {
  it('turns an untouched 70% default into no floor, so scored jobs are not hidden', () => {
    const migrated = migrateDiscoveryState({ filters: { minAtsScore: 70 } }, 3) as { filters: DiscoveryFilters };
    expect(migrated.filters.minAtsScore).toBe(0);
  });

  it('keeps a floor the person chose themselves', () => {
    const migrated = migrateDiscoveryState({ filters: { minAtsScore: 55 } }, 3) as { filters: DiscoveryFilters };
    expect(migrated.filters.minAtsScore).toBe(55);
  });

  it('new installs start with no floor', () => {
    expect(DEFAULT_FILTERS.minAtsScore).toBe(0);
  });
});
