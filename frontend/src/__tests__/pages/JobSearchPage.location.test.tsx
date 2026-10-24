/**
 * The Jobs screen under the UK-only policy: the facts line on every card, the location and
 * work-arrangement controls (which must reach the server, not just re-filter the page), the
 * hidden-jobs count, and paging past the first 100 results.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import JobSearchPage from '@/pages/JobSearchPage';
import { useDiscoveryStore, DEFAULT_FILTERS } from '@/store/useDiscoveryStore';
import { DEFAULT_ACTIVE_TITLES } from '@/lib/roleTargets';

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: 'j1', platform: 'reed', platform_job_id: 'r1', title: 'Senior Product Manager',
    company: 'Northwind Labs', location: 'EC4N6EU', url: 'https://x', description: 'Own it.',
    salary_range: null, job_type: 'Full-time', remote: false, posted_date: null,
    experience_level: 'Senior', match_score: 0.9, skills_required: null, status: 'new',
    created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z',
    sponsor_confidence: 'unknown', sponsor_evidence: null, sponsorship_status: 'not_specified',
    city: 'London', country_code: 'GB', country_name: 'United Kingdom', workplace_type: 'hybrid',
    uk_eligible: true, location_verification_status: 'verified', raw_location: 'EC4N6EU',
    posted_at: null, discovered_at: '2026-10-20T00:00:00Z',
    ...overrides,
  };
}

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

const last = <T,>(xs: T[]): T | undefined => xs[xs.length - 1];

/** Every `/jobs/` request the page makes, so tests can assert what reached the server. */
function captureListRequests(respond: (url: URL) => object) {
  const seen: URL[] = [];
  server.use(
    http.get('/api/v1/jobs/', ({ request }) => {
      const url = new URL(request.url);
      seen.push(url);
      return HttpResponse.json(respond(url));
    }),
  );
  return seen;
}

describe('Jobs under the UK-only policy', () => {
  beforeEach(() => {
    localStorage.removeItem('cvil-war-discovery');
    useDiscoveryStore.setState({
      activeTitles: DEFAULT_ACTIVE_TITLES, activeFamilies: [], enabledSources: [],
      filters: { ...DEFAULT_FILTERS, postedWithin: 'any' }, selectedJobIds: [],
      location: 'London, UK', query: '', recentSearches: [], appliedLocation: '', appliedQuery: '',
    });
  });

  it('puts employer, city and country, posting date and arrangement at the top of the card', async () => {
    captureListRequests(() => ({
      items: [job(), job({ id: 'j2', title: 'Group PM', posted_at: '2026-10-01T09:00:00Z', workplace_type: 'unspecified' })],
      total: 2, page: 1, page_size: 100, has_next: false,
    }));
    renderJobs();

    const first = (await screen.findByText('Senior Product Manager')).closest('.jc-card') as HTMLElement;
    const facts = within(first).getByText('London, United Kingdom').closest('.jc-facts') as HTMLElement;
    expect(facts).toHaveTextContent('Northwind Labs');
    expect(facts).toHaveTextContent('Posting date unavailable');
    expect(facts).toHaveTextContent('Hybrid');
    // The raw postcode is still available as evidence, not as the headline.
    expect(within(first).queryByText('EC4N6EU')).toBeNull();

    const second = screen.getByText('Group PM').closest('.jc-card') as HTMLElement;
    expect(second.querySelector('.jc-facts')).toHaveTextContent(/Posted 1 Oct 2026 \(\d+ days ago\)/);
    expect(second.querySelector('.jc-facts')).toHaveTextContent('Arrangement not stated');
  });

  it('sends the chosen city to the server, and "All UK" clears it', async () => {
    const seen = captureListRequests(() => ({ items: [job()], total: 1, page: 1, page_size: 100, has_next: false }));
    renderJobs();
    const user = userEvent.setup();
    const group = await screen.findByRole('group', { name: 'UK location' });

    await user.click(within(group).getByRole('button', { name: 'Manchester' }));
    await waitFor(() => expect(last(seen)?.searchParams.get('location')).toBe('Manchester'));
    expect(within(group).getByRole('button', { name: 'Manchester' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(within(group).getByRole('button', { name: 'All UK' }));
    await waitFor(() => expect(last(seen)?.searchParams.get('location')).toBeNull());
  });

  it('sends the work arrangement to the server', async () => {
    const seen = captureListRequests(() => ({ items: [job()], total: 1, page: 1, page_size: 100, has_next: false }));
    renderJobs();
    const user = userEvent.setup();
    const group = await screen.findByRole('group', { name: 'Work arrangement' });

    await user.click(within(group).getByRole('button', { name: 'UK remote' }));
    await waitFor(() => expect(last(seen)?.searchParams.get('workplace')).toBe('remote'));
    await user.click(within(group).getByRole('button', { name: 'Any' }));
    await waitFor(() => expect(last(seen)?.searchParams.get('workplace')).toBeNull());
  });

  it('says how many stored jobs the UK policy is keeping off the list', async () => {
    captureListRequests(() => ({ items: [job()], total: 1, page: 1, page_size: 100, has_next: false }));
    renderJobs();
    // From the location-summary mock: 2 outside the UK, 1 quarantined.
    expect(await screen.findByText(/UK roles only · 2 outside the UK hidden · 1 with an unverified location/)).toBeInTheDocument();
  });

  it('pages through results on the server instead of stopping at the first 100', async () => {
    const seen = captureListRequests((url) => {
      const page = Number(url.searchParams.get('page'));
      return { items: [job({ id: `p${page}`, title: `Role on page ${page}` })], total: 250, page, page_size: 100, has_next: page < 3 };
    });
    renderJobs();
    const user = userEvent.setup();

    expect(await screen.findByText('Role on page 1')).toBeInTheDocument();
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Role on page 2')).toBeInTheDocument();
    expect(last(seen)?.searchParams.get('page')).toBe('2');
    expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled();
  });

  it('returns to page 1 when the location changes', async () => {
    const seen = captureListRequests((url) => {
      const page = Number(url.searchParams.get('page'));
      return { items: [job({ id: `p${page}`, title: `Role on page ${page}` })], total: 250, page, page_size: 100, has_next: true };
    });
    renderJobs();
    const user = userEvent.setup();
    await screen.findByText('Role on page 1');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Role on page 2');

    await user.click(within(screen.getByRole('group', { name: 'UK location' })).getByRole('button', { name: 'Leeds' }));
    await waitFor(() => {
      const latest = last(seen);
      expect(latest?.searchParams.get('location')).toBe('Leeds');
      expect(latest?.searchParams.get('page')).toBe('1');
    });
  });
});
