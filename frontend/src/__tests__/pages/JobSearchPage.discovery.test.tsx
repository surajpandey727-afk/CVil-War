/**
 * The Jobs screen's discovery controls: which sources it offers, how it filters on pay and
 * sponsorship, and the search history.
 *
 * Kept apart from `JobSearchPage.test.tsx`, which covers the list and the apply flow, because
 * these three concerns share one thing the older suite does not exercise at all: they read the
 * canonical job fields the server derives, and every defect they pin came from something
 * deriving those fields for itself instead.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import JobSearchPage from '@/pages/JobSearchPage';
import { useDiscoveryStore, DEFAULT_FILTERS } from '@/store/useDiscoveryStore';
import { DEFAULT_ACTIVE_TITLES } from '@/lib/roleTargets';
import { SALARY_BRACKETS } from '@/lib/jobModel';

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: 'j1', platform: 'remotive', platform_job_id: 'rm1', title: 'Senior Product Manager',
    company: 'Northwind Labs', location: 'London, UK', url: 'https://x',
    description: 'Own the roadmap.', salary_range: null, job_type: 'Full-time', remote: true,
    posted_date: null, experience_level: 'Senior', match_score: 0.9, skills_required: null,
    status: 'new', created_at: '2026-08-08T00:00:00Z', updated_at: '2026-08-08T00:00:00Z',
    sponsor_confidence: 'unknown', sponsor_evidence: null, sponsorship_status: 'not_specified',
    ...overrides,
  };
}

const listOf = (...items: object[]) =>
  ({ items, total: items.length, page: 1, page_size: 20, has_next: false });

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

describe('Jobs discovery controls', () => {
  // The store is persisted, so clearing storage before resetting is what makes the reset
  // final — a rehydrate scheduled before the reset can otherwise land after it. See the
  // longer note in JobSearchPage.test.tsx.
  beforeEach(() => {
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({
      activeTitles: DEFAULT_ACTIVE_TITLES,
      activeFamilies: [],
      enabledSources: [],
      filters: DEFAULT_FILTERS,
      selectedJobIds: [],
      location: 'London, UK',
      query: '',
      recentSearches: [],
      appliedLocation: '',
      appliedQuery: '',
    });
  });

  /* -------------------------------------------------------------------------------------
   * Sources rail
   *
   * It was built from the static catalogue in lib/sources and then truncated to the first
   * six entries per tier. Of 69 career-page sources, six were reachable; the other 63 could
   * neither be seen nor toggled. It also listed unbuilt and signed-out sources inline with a
   * "SOON" tag, so most of what was on screen could not return a result.
   * ---------------------------------------------------------------------------------- */
  describe('the sources rail shows what can actually be searched', () => {
    it('lists the sources that can return results now', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      expect(await screen.findByRole('button', { name: /^Remotive/ })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^Adzuna/ })).toBeInTheDocument();
    });

    it('keeps a source with no working adapter out of the rail', async () => {
      // ukvisajobs is in the catalogue but not in live_keys: its real listing is behind a
      // login. Offering it invites the operator to enable a source that can only ever return
      // nothing, which then reads as "no jobs in London" rather than "not wired up".
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await screen.findByRole('button', { name: /^Remotive/ });
      expect(screen.queryByRole('button', { name: /UK Visa Jobs/ })).not.toBeInTheDocument();
    });

    it('says how many are behind Manage rather than dropping them silently', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      expect(await screen.findByRole('button', { name: /1 more in Manage/ })).toBeInTheDocument();
    });

    it('renders the live registry, not the static catalogue', async () => {
      // The static file lists LinkedIn, Indeed, Glassdoor and 69 career pages. None are in
      // the mocked registry, and the rail must follow the registry.
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await screen.findByRole('button', { name: /^Remotive/ });
      expect(screen.queryByRole('button', { name: /LinkedIn Jobs/ })).not.toBeInTheDocument();
    });

    it('hides a source Settings has switched off', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      server.use(
        http.get('/api/v1/settings/', () =>
          HttpResponse.json({
            id: 'settings-1', default_template: 'modern', auto_apply: false,
            platforms: [], llm_provider: 'openai', platforms_enabled: ['remotive'],
          })),
      );
      renderJobs();

      await screen.findByRole('button', { name: /^Remotive/ });
      await waitFor(() =>
        expect(screen.queryByRole('button', { name: /^Adzuna/ })).not.toBeInTheDocument(),
      );
    });

    it('every rail source reads as on while the selection is empty', async () => {
      // An empty selection means "search everything". Rendering every row greyed out until
      // something is ticked told the operator the opposite of what the search would do.
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      expect(await screen.findByRole('button', { name: /^Remotive/ }))
        .toHaveAttribute('aria-pressed', 'true');
    });

    it('switching one off while the selection is empty excludes only that one', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.click(await screen.findByRole('button', { name: /^Remotive/ }));

      expect(useDiscoveryStore.getState().enabledSources).toEqual(['adzuna']);
    });

    it('switching the last one back on returns to "everything" rather than a frozen list', async () => {
      // Storing the full list instead would silently exclude any source added to the
      // registry later — the operator would never know a new board existed.
      useDiscoveryStore.setState({ enabledSources: ['adzuna'] });
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.click(await screen.findByRole('button', { name: /^Remotive/ }));

      expect(useDiscoveryStore.getState().enabledSources).toEqual([]);
    });
  });

  /* -------------------------------------------------------------------------------------
   * Salary
   *
   * The old client-side parser took the smallest number anywhere in the salary string, so
   * "Up to £60,000 + 10% bonus" filtered as £10k and "£500 per day" as £500k. The card showed
   * the posting's own text, so the card and the filter disagreed with nothing on screen to
   * say so.
   * ---------------------------------------------------------------------------------- */
  describe('salary filtering reads the canonical band', () => {
    const paid = (overrides: Record<string, unknown> = {}) =>
      job({
        salary_range: 'Up to £60,000 + 10% bonus',
        salary_min: null, salary_max: 60_000, salary_currency: 'GBP',
        salary_period: 'year', salary_annualised: false,
        ...overrides,
      });

    it('a £60k role survives a £50k floor even though its text contains "10%"', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, salaryCustomMinK: 50 } });
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(paid()))));
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Senior Product Manager' }))
        .toBeInTheDocument();
    });

    it('the card shows the same figure the filter used', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(paid()))));
      renderJobs();

      await screen.findByRole('button', { name: 'Senior Product Manager' });
      expect(screen.getByText('Up to £60k')).toBeInTheDocument();
    });

    it('a bracket keeps a role whose band overlaps it', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, salaryBrackets: ['50-60'] } });
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(paid({ salary_min: 55_000, salary_max: 85_000 })))));
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Senior Product Manager' }))
        .toBeInTheDocument();
    });

    it('a bracket removes a role whose band falls entirely outside it', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, salaryBrackets: ['20-30'] } });
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(paid({ salary_min: 90_000, salary_max: 110_000 })))));
      renderJobs();

      expect(await screen.findByText(/no roles match these filters/i)).toBeInTheDocument();
    });

    it('a role that publishes no salary is never removed by a salary window', async () => {
      // Most UK postings publish nothing. Treating them as £0 would hide the majority of the
      // market behind a filter the operator only meant to narrow it with.
      useDiscoveryStore.setState({
        filters: { ...DEFAULT_FILTERS, salaryBrackets: ['75+'], salaryCustomMinK: 80 },
      });
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(job({ salary_range: 'Competitive' })))));
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Senior Product Manager' }))
        .toBeInTheDocument();
      // The posting's own word, not a substitute for it.
      expect(screen.getByText('Competitive')).toBeInTheDocument();
    });

    it('"Published salary only" is the control that removes them, and it says so', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, publishedSalaryOnly: true } });
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(job({ salary_range: 'Competitive' })))));
      renderJobs();

      expect(await screen.findByText('Published salary only')).toBeInTheDocument();
    });

    it('names the salary bracket as the culprit and clearing it brings the role back', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, salaryBrackets: ['20-30'] } });
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(paid({ salary_min: 90_000, salary_max: 110_000 })))));
      renderJobs();

      expect(await screen.findByText('Salary brackets')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Clear' }));

      expect(await screen.findByRole('button', { name: 'Senior Product Manager' }))
        .toBeInTheDocument();
    });

    it('sorts by the band rather than by whichever number came first', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, sort: 'salary' } });
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(
          job({ id: 'low', title: 'Lower paid', salary_range: 'Up to £60,000 + 10% bonus', salary_max: 60_000 }),
          job({
            id: 'high', title: 'Higher paid', salary_range: '£500 per day',
            salary_min: 110_000, salary_max: 110_000, salary_annualised: true,
          }),
        ))));
      renderJobs();

      await screen.findByRole('button', { name: 'Higher paid' });
      const titles = screen.getAllByRole('button', { name: /paid$/ }).map((el) => el.textContent);
      expect(titles).toEqual(['Higher paid', 'Lower paid']);
    });

    it('says when a figure was annualised rather than quoted by the employer', async () => {
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(job({
          salary_range: '£500 per day', salary_min: 110_000, salary_max: 110_000,
          salary_period: 'day', salary_annualised: true,
        })))));
      renderJobs();

      await screen.findByRole('button', { name: 'Senior Product Manager' });
      expect(screen.getByTitle(/yearly equivalent/i)).toBeInTheDocument();
    });
  });

  /* -------------------------------------------------------------------------------------
   * Sponsorship
   * ---------------------------------------------------------------------------------- */
  describe('visa sponsorship filtering', () => {
    it('shows the sponsorship answer on every card, including "not specified"', async () => {
      // It used to be hidden whenever it was unknown. Once sponsorship became a filter, a
      // candidate filtering for "not specified" had no way to see why a row was in their
      // results.
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await screen.findByRole('button', { name: 'Senior Product Manager' });
      expect(screen.getByText('Not stated')).toBeInTheDocument();
    });

    // Role titles here deliberately avoid the words on the sponsorship filter chips.
    // They did not, and `findByRole('button', { name: 'Sponsors' })` resolved against the
    // filter chip instead of the job row -- so the assertion that followed it ran before any
    // job had rendered, and "the excluded role is absent" passed because nothing was there
    // yet. A test that cannot fail is worse than no test.
    it('keeps only sponsoring employers when that is the filter', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, sponsorship: ['available'] } });
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(
          job({ id: 'y', title: 'Sponsoring employer', sponsor_confidence: 'confirmed_register', sponsorship_status: 'available' }),
          job({ id: 'n', title: 'Silent employer' }),
        ))));
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Sponsoring employer' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Silent employer' })).not.toBeInTheDocument();
    });

    it('a posting that says nothing is not counted as a refusal', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, sponsorship: ['none'] } });
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      expect(await screen.findByText(/no roles match these filters/i)).toBeInTheDocument();
    });

    it('selecting two answers is an OR', async () => {
      useDiscoveryStore.setState({
        filters: { ...DEFAULT_FILTERS, sponsorship: ['available', 'not_specified'] },
      });
      server.use(http.get('/api/v1/jobs/', () =>
        HttpResponse.json(listOf(
          job({ id: 'y', title: 'Sponsoring employer', sponsorship_status: 'available' }),
          job({ id: 'q', title: 'Silent employer' }),
          job({ id: 'n', title: 'Refusing employer', sponsorship_status: 'none' }),
        ))));
      renderJobs();

      expect(await screen.findByRole('button', { name: 'Sponsoring employer' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Silent employer' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Refusing employer' })).not.toBeInTheDocument();
    });

    it('names sponsorship as the culprit when it is what emptied the list', async () => {
      useDiscoveryStore.setState({ filters: { ...DEFAULT_FILTERS, sponsorship: ['none'] } });
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      expect(await screen.findByText('Visa sponsorship')).toBeInTheDocument();
    });
  });

  /* -------------------------------------------------------------------------------------
   * Recent searches
   * ---------------------------------------------------------------------------------- */
  describe('recent searches', () => {
    it('says what the list is for before there is anything in it', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      expect(await screen.findByText(/searches you run appear here/i)).toBeInTheDocument();
    });

    it('records a search that was actually run, with the sources it used', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
      server.use(http.post('/api/v1/jobs/search', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.type(screen.getByLabelText(/job title or keywords/i), 'ml engineer');
      await userEvent.click(screen.getByRole('button', { name: /^search$/i }));

      expect(await screen.findByRole('button', { name: /Re-run this search: ml engineer/ }))
        .toBeInTheDocument();
      await waitFor(() =>
        expect(useDiscoveryStore.getState().recentSearches[0]!.sources)
          .toEqual(['remotive', 'adzuna']),
      );
    });

    it('shows how many the search returned once it comes back', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
      server.use(http.post('/api/v1/jobs/search', () =>
        HttpResponse.json(listOf(job(), job({ id: 'j2' })))));
      renderJobs();

      await userEvent.type(screen.getByLabelText(/job title or keywords/i), 'ml engineer');
      await userEvent.click(screen.getByRole('button', { name: /^search$/i }));

      expect(await screen.findByText(/2 found/)).toBeInTheDocument();
    });

    it('re-running one restores the conditions it was run under and searches again', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
      let sent: { query?: string; platforms?: string[] } | null = null;
      server.use(http.post('/api/v1/jobs/search', async ({ request }) => {
        sent = (await request.json()) as { query: string; platforms: string[] };
        return HttpResponse.json(listOf());
      }));
      useDiscoveryStore.setState({
        recentSearches: [{
          id: 'sig', query: 'Applied Scientist', location: 'Cambridge', sources: ['remotive'],
          filters: { ...DEFAULT_FILTERS, salaryBrackets: ['75+'], sponsorship: ['available'] },
          at: Date.now(), resultCount: 12,
        }],
      });
      renderJobs();

      await userEvent.click(
        await screen.findByRole('button', { name: /Re-run this search: Applied Scientist/ }),
      );

      await waitFor(() => expect(sent).not.toBeNull());
      expect(sent!.query).toBe('Applied Scientist');
      expect(sent!.platforms).toEqual(['remotive']);
      const filters = useDiscoveryStore.getState().filters;
      expect(filters.salaryBrackets).toEqual(['75+']);
      expect(filters.sponsorship).toEqual(['available']);
    });

    it('removes one entry without touching the rest', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
      useDiscoveryStore.setState({
        recentSearches: [
          { id: 'a', query: 'First search', location: '', sources: [], filters: DEFAULT_FILTERS, at: Date.now(), resultCount: 1 },
          { id: 'b', query: 'Second search', location: '', sources: [], filters: DEFAULT_FILTERS, at: Date.now(), resultCount: 2 },
        ],
      });
      renderJobs();

      await userEvent.click(
        await screen.findByRole('button', { name: /Remove First search from recent searches/ }),
      );

      expect(useDiscoveryStore.getState().recentSearches.map((r) => r.query))
        .toEqual(['Second search']);
    });

    it('survives a reload rather than resetting to a placeholder', async () => {
      // The whole point of the feature. A history that empties on refresh is a placeholder
      // with extra steps, which is what was on this screen before.
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
      server.use(http.post('/api/v1/jobs/search', () => HttpResponse.json(listOf(job()))));
      const first = renderJobs();

      await userEvent.type(screen.getByLabelText(/job title or keywords/i), 'remote ml');
      await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
      await screen.findByRole('button', { name: /Re-run this search: remote ml/ });

      first.unmount();
      const persisted = JSON.parse(localStorage.getItem('cvil-war-discovery')!);
      expect(persisted.state.recentSearches[0].query).toBe('remote ml');

      renderJobs();
      expect(await screen.findByRole('button', { name: /Re-run this search: remote ml/ }))
        .toBeInTheDocument();
    });
  });

  /* -------------------------------------------------------------------------------------
   * The controls themselves
   *
   * Everything above sets filter state directly. That proves the filter works and says
   * nothing about whether the operator can reach it -- a chip that is never rendered, or
   * rendered but not wired to the store, passes all of it.
   * ---------------------------------------------------------------------------------- */
  describe('the advanced filters are reachable and wired', () => {
    it('a salary bracket chip is on screen and toggles the filter', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.click(await screen.findByRole('button', { name: '£60–75k' }));
      expect(useDiscoveryStore.getState().filters.salaryBrackets).toEqual(['60-75']);

      await userEvent.click(screen.getByRole('button', { name: '£60–75k' }));
      expect(useDiscoveryStore.getState().filters.salaryBrackets).toEqual([]);
    });

    it('every bracket in the model has a chip', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await screen.findByRole('button', { name: '£20–30k' });
      for (const bracket of SALARY_BRACKETS) {
        expect(screen.getByRole('button', { name: bracket.label })).toBeInTheDocument();
      }
    });

    it('the custom window takes a figure and records it in thousands', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.type(
        await screen.findByLabelText(/custom minimum salary/i), '65',
      );
      await waitFor(() =>
        expect(useDiscoveryStore.getState().filters.salaryCustomMinK).toBe(65),
      );
    });

    it('clearing the custom window means unbounded, not zero', async () => {
      // A £0 floor and no floor look identical on screen but behave very differently the
      // moment anything reads the value as a minimum.
      useDiscoveryStore.setState({
        filters: { ...DEFAULT_FILTERS, salaryCustomMinK: 65 },
      });
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.clear(await screen.findByLabelText(/custom minimum salary/i));
      await waitFor(() =>
        expect(useDiscoveryStore.getState().filters.salaryCustomMinK).toBeNull(),
      );
    });

    it('the custom window ignores anything that is not a number', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.type(await screen.findByLabelText(/custom maximum salary/i), 'abc90k');
      await waitFor(() =>
        expect(useDiscoveryStore.getState().filters.salaryCustomMaxK).toBe(90),
      );
    });

    it('all three sponsorship answers are offered as chips', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await screen.findByRole('button', { name: 'Sponsors' });
      expect(screen.getByRole('button', { name: 'Not specified' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'No sponsorship' })).toBeInTheDocument();
    });

    it('a sponsorship chip toggles the filter', async () => {
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.click(await screen.findByRole('button', { name: 'Sponsors' }));
      expect(useDiscoveryStore.getState().filters.sponsorship).toEqual(['available']);
    });

    it('resetting the filters clears the new ones too', async () => {
      // A reset that leaves some filters set is worse than none: the operator believes the
      // list is unfiltered and it is not.
      useDiscoveryStore.setState({
        filters: {
          ...DEFAULT_FILTERS,
          salaryBrackets: ['75+'], salaryCustomMinK: 80, salaryCustomMaxK: 120,
          sponsorship: ['available'],
        },
      });
      server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
      renderJobs();

      await userEvent.click(await screen.findByRole('button', { name: /reset filters/i }));

      const filters = useDiscoveryStore.getState().filters;
      expect(filters.salaryBrackets).toEqual([]);
      expect(filters.sponsorship).toEqual([]);
      expect(filters.salaryCustomMinK).toBeNull();
      expect(filters.salaryCustomMaxK).toBeNull();
    });
  });
});
