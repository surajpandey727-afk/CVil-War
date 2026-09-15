import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import JobSearchPage from '@/pages/JobSearchPage';
import { useDiscoveryStore, DEFAULT_FILTERS } from '@/store/useDiscoveryStore';
import { WORKING_SOURCE_KEYS } from '@/lib/sources';
import { DEFAULT_ACTIVE_TITLES } from '@/lib/roleTargets';

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: 'j1', platform: 'remotive', platform_job_id: 'rm1', title: 'Senior Product Manager',
    company: 'Northwind Labs', location: 'London, UK', url: 'https://x', description: 'Own the roadmap.',
    salary_range: null, job_type: 'Full-time', remote: true, posted_date: null,
    experience_level: 'Senior', match_score: 0.9, skills_required: null, status: 'new',
    created_at: '2026-08-08T00:00:00Z', updated_at: '2026-08-08T00:00:00Z', ...overrides,
  };
}
const listOf = (...items: object[]) => ({ items, total: items.length, page: 1, page_size: 20, has_next: false });

function renderJobs() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobSearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('JobSearchPage', () => {
  // The discovery store is persisted, so state written by one test leaks into the next.
  //
  // Resetting via setState alone is NOT enough and was intermittently failing roughly one run
  // in three: zustand's persist middleware rehydrates from localStorage asynchronously, so a
  // rehydrate scheduled before the reset could land *after* it and restore the previous
  // test's state. The "switch a source off" test persists remotive:off, so whichever test ran
  // next would occasionally render zero rows and fail looking for a job title.
  //
  // Clearing the storage first removes what rehydration would restore, making the reset final.
  beforeEach(() => {
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({
      activeTitles: DEFAULT_ACTIVE_TITLES,
      activeFamilies: [],
      enabledSources: WORKING_SOURCE_KEYS,
      filters: DEFAULT_FILTERS,
      selectedJobIds: [],
      location: 'London, UK',
      query: '',
      appliedLocation: '',
      appliedQuery: '',
    });
  });

  it('renders job rows from the API', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
    renderJobs();
    expect(await screen.findByRole('button', { name: 'Senior Product Manager' })).toBeInTheDocument();
    expect(screen.getByText(/Northwind Labs/)).toBeInTheDocument();
  });

  it('searches with the typed query', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
    let body: { query?: string; platforms?: string[] } | null = null;
    server.use(http.post('/api/v1/jobs/search', async ({ request }) => {
      body = (await request.json()) as { query: string; platforms: string[] };
      return HttpResponse.json(listOf());
    }));
    renderJobs();
    await userEvent.type(screen.getByLabelText(/job title or keywords/i), 'product manager');
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.query).toBe('product manager');
  });

  it('sends only sources with a working adapter to the search endpoint', async () => {
    // A catalogue entry with no adapter costs a guaranteed-empty round trip, and an empty
    // result set then reads as a market signal rather than an unbuilt integration.
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
    let platforms: string[] = [];
    server.use(http.post('/api/v1/jobs/search', async ({ request }) => {
      platforms = ((await request.json()) as { platforms: string[] }).platforms;
      return HttpResponse.json(listOf());
    }));
    // ukvisajobs/otta have no adapter yet (both confirmed unimplemented — see lib/sources.ts);
    // reed and careers:monzo were the same kind of example until their adapters shipped,
    // which is exactly the staleness this file's own cleanup comment now warns about.
    useDiscoveryStore.setState({ enabledSources: [...WORKING_SOURCE_KEYS, 'ukvisajobs', 'otta'] });
    renderJobs();
    await userEvent.type(screen.getByLabelText(/job title or keywords/i), 'ml engineer');
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    await waitFor(() => expect(platforms.length).toBeGreaterThan(0));
    expect(platforms).not.toContain('ukvisajobs');
    expect(platforms).not.toContain('otta');
    expect(platforms).toContain('remotive');
  });

  it('searches every live source rather than blocking, for a visitor who has never touched the source filter', async () => {
    // Regression test for a real bug: enabledSources defaults to [] for anyone who has
    // never opened the per-device source filter, and this used to hard-block the search
    // with "None of the enabled sources have a working adapter yet" — discovery, the
    // screen's one job, refused to run at all on a first visit.
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
    let platforms: string[] = [];
    server.use(http.post('/api/v1/jobs/search', async ({ request }) => {
      platforms = ((await request.json()) as { platforms: string[] }).platforms;
      return HttpResponse.json(listOf());
    }));
    useDiscoveryStore.setState({ enabledSources: [] });
    renderJobs();
    await userEvent.type(screen.getByLabelText(/job title or keywords/i), 'ml engineer');
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    await waitFor(() => expect(platforms.length).toBeGreaterThan(0));
    expect(platforms).toEqual(['remotive', 'adzuna']); // the mocked catalogue's live_keys
  });

  it('excludes jobs from a source the operator switched off', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
    renderJobs();
    await screen.findByRole('button', { name: 'Senior Product Manager' });
    await userEvent.click(screen.getByRole('button', { name: /^Remotive/ }));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Senior Product Manager' })).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/no roles match these filters/i)).toBeInTheDocument();
  });

  it('filters out roles below the ATS threshold', async () => {
    server.use(http.get('/api/v1/jobs/', () =>
      HttpResponse.json(listOf(job(), job({ id: 'j2', title: 'Junior Analyst', match_score: 0.42 })))));
    renderJobs();
    await screen.findByRole('button', { name: 'Senior Product Manager' });
    expect(screen.queryByRole('button', { name: 'Junior Analyst' })).not.toBeInTheDocument();
  });

  it('distinguishes "filtered out" from "nothing stored"', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
    renderJobs();
    expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/no roles match these filters/i)).not.toBeInTheDocument();
  });

  it('says nothing matches the search rather than "no jobs yet" when one is applied', async () => {
    // A third state, and the one that appears in practice: jobs exist, but none in the
    // requested place. Rendering that as "No jobs yet" reads as a broken app rather than as
    // a prompt to run the search.
    useDiscoveryStore.setState({ appliedLocation: 'London, UK' });
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
    renderJobs();

    expect(await screen.findByText(/nothing stored matches that search/i)).toBeInTheDocument();
    expect(screen.getByText(/in London, UK/)).toBeInTheDocument();
  });

  it('sends the applied location to the server rather than filtering in the browser', async () => {
    // The London bug in one assertion: the request carried no location, so the backend
    // returned every stored job and the page rendered them all.
    let seen: URLSearchParams | null = null;
    useDiscoveryStore.setState({ appliedLocation: 'London, UK', appliedQuery: 'Product Manager' });
    server.use(
      http.get('/api/v1/jobs/', ({ request }) => {
        seen = new URL(request.url).searchParams;
        return HttpResponse.json(listOf(job()));
      }),
    );
    renderJobs();
    await screen.findByRole('button', { name: 'Senior Product Manager' });

    expect(seen!.get('location')).toBe('London, UK');
    expect(seen!.get('q')).toBe('Product Manager');
  });

  it('queues a whole selection through the batch endpoint', async () => {
    server.use(http.get('/api/v1/jobs/', () =>
      HttpResponse.json(listOf(job(), job({ id: 'j2', title: 'Staff ML Engineer' })))));
    let body: { job_ids?: string[]; apply_mode?: string } | null = null;
    server.use(http.post('/api/v1/applications/batch', async ({ request }) => {
      body = (await request.json()) as { job_ids: string[]; apply_mode: string };
      return HttpResponse.json([], { status: 201 });
    }));
    renderJobs();
    await screen.findByRole('button', { name: 'Senior Product Manager' });

    const selectAll = screen.getAllByRole('button', { name: /roles ·/i })[0]!;
    await userEvent.click(selectAll);
    await userEvent.click(await screen.findByRole('button', { name: /start applying/i }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.job_ids).toEqual(['j1', 'j2']);
    expect(body!.apply_mode).toBe('review');
  });

  it('opens the job as the decision centre when its title is clicked', async () => {
    // The drawer no longer fires an analysis on open. Analysing every job the operator
    // glances at would spend a model call per click; the CV is chosen first, in the drawer,
    // and the assessment is an explicit action.
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
    renderJobs();

    await userEvent.click(await screen.findByRole('button', { name: 'Senior Product Manager' }));

    const drawer = await screen.findByRole('dialog', { name: /job details/i });
    expect(drawer).toBeInTheDocument();
    expect(await screen.findByLabelText('CV')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /analyse my fit/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /apply with agent/i })).toBeInTheDocument();
  });

  it('a manual search respects sources disabled in Settings, not just adapter health', async () => {
    // Settings/Sources also gates the background discovery worker via `platforms_enabled`.
    // Previously, the moment the per-device source filter (enabledSources) was untouched,
    // a manual search here fell back to every adapter-healthy source regardless of that
    // setting — disabling a source in Settings had no effect on what a manual search
    // actually searched, which is the opposite of what disabling it means.
    useDiscoveryStore.setState({ enabledSources: [] });
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
    server.use(
      http.get('/api/v1/settings/', () =>
        HttpResponse.json({
          id: 'settings-1', default_template: 'modern', auto_apply: false,
          platforms: [], llm_provider: 'openai', platforms_enabled: ['remotive'],
        })),
    );
    let sentPlatforms: string[] | null = null;
    server.use(
      http.post('/api/v1/jobs/search', async ({ request }) => {
        const b = (await request.json()) as { platforms?: string[] };
        sentPlatforms = b.platforms ?? null;
        return HttpResponse.json(listOf(job()));
      }),
    );
    renderJobs();
    await screen.findByRole('button', { name: 'Senior Product Manager' });

    await userEvent.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(sentPlatforms).not.toBeNull());
    expect(sentPlatforms).toContain('remotive');
    expect(sentPlatforms).not.toContain('adzuna');
  });

  describe('jobs are not hidden by a stale source catalogue', () => {
    // The defect these pin: the static catalogue in lib/sources marks every `careers:*`
    // entry not_implemented, which was false for nine of them. The page filtered against
    // that list, so 28 of 55 real London jobs vanished with no message — the operator saw an
    // empty screen and concluded search was broken. Every existing test passed because the
    // fixtures all used `platform: 'linkedin'`, which happens to be in the stale list.

    it('shows a job from a career-page source', async () => {
      useDiscoveryStore.setState({ enabledSources: [] });
      server.use(
        http.get('/api/v1/jobs/', () =>
          HttpResponse.json(listOf(job({ id: 'c1', platform: 'careers:wise', title: 'Product Owner' }))),
        ),
      );
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Product Owner' })).toBeInTheDocument();
    });

    it('shows a job whose source the frontend catalogue has never heard of', async () => {
      // A source added to the backend must appear immediately, not after a frontend release.
      useDiscoveryStore.setState({ enabledSources: [] });
      server.use(
        http.get('/api/v1/jobs/', () =>
          HttpResponse.json(listOf(job({ id: 'n1', platform: 'brand-new-board', title: 'Fresh Role' }))),
        ),
      );
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Fresh Role' })).toBeInTheDocument();
    });

    it('an empty selection means every source, not no sources', async () => {
      useDiscoveryStore.setState({ enabledSources: [] });
      server.use(
        http.get('/api/v1/jobs/', () =>
          HttpResponse.json(listOf(
            job({ id: 'a', platform: 'arbeitnow', title: 'Role A' }),
            job({ id: 'b', platform: 'careers:monzo', title: 'Role B' }),
          )),
        ),
      );
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Role A' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Role B' })).toBeInTheDocument();
    });

    it('still honours a source the operator has explicitly switched off', async () => {
      // The filter must keep working — the fix is that it only applies the operator's own
      // choices, not a stale guess about what exists.
      useDiscoveryStore.setState({ enabledSources: ['remotive'] });
      // The registry has to know about linkedin for "known and switched off" to be the case
      // under test — an unrecognised source is deliberately kept.
      server.use(
        http.get('/api/v1/sources/', () =>
          HttpResponse.json({
            total: 2,
            live_keys: ['remotive'],
            tiers: [{
              id: 'aggregator', label: 'Aggregators', name: 'Aggregators', note: '',
              sources: [
                { key: 'remotive', label: 'Remotive', health: 'live', implemented: true },
                { key: 'linkedin', label: 'LinkedIn', health: 'degraded', implemented: true },
              ],
            }],
          }),
        ),
      );
      server.use(
        http.get('/api/v1/jobs/', () =>
          HttpResponse.json(listOf(
            job({ id: 'a', platform: 'remotive', title: 'Kept Role' }),
            job({ id: 'b', platform: 'linkedin', title: 'Excluded Role' }),
          )),
        ),
      );
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Kept Role' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Excluded Role' })).not.toBeInTheDocument();
    });
  });

  describe('naming the filter that is hiding the jobs', () => {
    // The screen said "23 stored roles were filtered out" and left the operator to guess which
    // of eight controls did it. It was a remote-only toggle set days earlier and forgotten.
    //
    // These assert through the Clear button rather than the filter's name: the sidebar carries
    // the same words as a checkbox label, so matching on text alone passes even when the
    // diagnostic panel is absent — which is exactly how the first version of these tests
    // fooled itself.
    const pristine = useDiscoveryStore.getState().filters;
    beforeEach(() => {
      useDiscoveryStore.setState({
        filters: { ...pristine }, activeFamilies: [], enabledSources: [],
      });
    });

    it('names the filter and how many roles it removed', async () => {
      useDiscoveryStore.setState({ filters: { ...pristine, remoteOnly: true } });
      server.use(
        http.get('/api/v1/jobs/', () =>
          HttpResponse.json(listOf(
            job({ id: 'a', title: 'Onsite One', remote: false }),
            job({ id: 'b', title: 'Onsite Two', remote: false }),
          )),
        ),
      );
      renderJobs();

      const clear = await screen.findByRole('button', { name: 'Clear' });
      const row = clear.parentElement!;
      expect(row).toHaveTextContent('Remote or hybrid only');
      expect(row).toHaveTextContent('2 hidden');
    });

    it('clearing the named filter brings the jobs back', async () => {
      useDiscoveryStore.setState({ filters: { ...pristine, remoteOnly: true } });
      server.use(
        http.get('/api/v1/jobs/', () =>
          HttpResponse.json(listOf(job({ id: 'a', title: 'Onsite One', remote: false }))),
        ),
      );
      renderJobs();

      await userEvent.click(await screen.findByRole('button', { name: 'Clear' }));

      expect(await screen.findByRole('button', { name: 'Onsite One' })).toBeInTheDocument();
    });

    it('charges each hidden role to exactly one filter', async () => {
      // Two filters can both reject the same role; counting it twice would report more hidden
      // roles than exist and make every number on the panel untrustworthy.
      useDiscoveryStore.setState({
        filters: { ...pristine, remoteOnly: true, publishedSalaryOnly: true },
      });
      server.use(
        http.get('/api/v1/jobs/', () =>
          HttpResponse.json(listOf(
            job({ id: 'a', title: 'A', remote: false, salary_range: null }),
          )),
        ),
      );
      renderJobs();

      await screen.findByRole('button', { name: 'Clear' });
      expect(screen.getAllByRole('button', { name: 'Clear' })).toHaveLength(1);
    });

    it('offers no diagnostic when nothing is stored to hide', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
      renderJobs();

      expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();
    });
  });
});
