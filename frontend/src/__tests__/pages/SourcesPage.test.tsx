import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import SourcesPage from '@/pages/SourcesPage';
import { useDiscoveryStore } from '@/store/useDiscoveryStore';

const CATALOGUE_RESPONSE = {
  total: 2,
  tiers: [
    {
      id: 'tier1', name: 'Must-use boards', note: '',
      sources: [
        { key: 'reed', label: 'Reed', domain: 'reed.co.uk', tier: 'tier1', implemented: true, health: 'live', note: '' },
        { key: 'adzuna', label: 'Adzuna', domain: 'adzuna.co.uk', tier: 'tier1', implemented: true, health: 'live', note: '' },
      ],
    },
  ],
  live_keys: ['reed', 'adzuna'],
};

function renderSources() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SourcesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SourcesPage', () => {
  beforeEach(() => {
    localStorage.clear();
    useDiscoveryStore.setState({ enabledSources: [] });
  });

  // Regression test: the live catalogue reports every health value the backend registry can
  // produce (`app.core.job_discovery.source_registry.SourceHealth` has 7 members), but the
  // frontend's health-to-label map once covered only 4 of them. A source in any of the missing
  // states (e.g. Civil Service Jobs, reported `interactive_available` once it needs a one-time
  // browser sign-in) made `HEALTH_META[health]` come back `undefined` and crashed the whole
  // page — "I can't open it" — rather than just failing to render that one card. This renders
  // every real health value the backend can send and asserts the page comes up at all.
  it('renders every source health the backend can report without crashing', async () => {
    server.use(
      http.get('/api/v1/sources/', () => {
        const sources = [
          { key: 'reed', label: 'Reed', domain: 'reed.co.uk', tier: 'tier1', implemented: true, health: 'live', note: '' },
          { key: 'adzuna', label: 'Adzuna', domain: 'adzuna.co.uk', tier: 'tier1', implemented: true, health: 'degraded', note: 'Slow lately' },
          { key: 'linkedin', label: 'LinkedIn', domain: 'linkedin.com', tier: 'tier1', implemented: true, health: 'auth_required', note: '' },
          { key: 'exa', label: 'Exa', domain: 'exa.ai', tier: 'tier2', implemented: true, health: 'rate_limited', note: '' },
          {
            key: 'civilservice', label: 'Civil Service Jobs', domain: 'civilservicejobs.service.gov.uk',
            tier: 'tier2', implemented: false, health: 'interactive_available',
            note: 'Connect this in Settings, then discovery can be built.',
          },
          { key: 'someboard', label: 'Some Board', domain: 'someboard.example', tier: 'tier2', implemented: false, health: 'unavailable', note: 'Blocked' },
          { key: 'careers:acme', label: 'Acme', domain: 'acme.example', tier: 'careers', implemented: false, health: 'not_implemented', note: '' },
        ];
        return HttpResponse.json({
          total: sources.length,
          tiers: [
            { id: 'tier1', name: 'Must-use boards', note: '', sources: sources.slice(0, 3) },
            { id: 'tier2', name: 'UK boards', note: '', sources: sources.slice(3, 6) },
            { id: 'careers', name: 'Company career pages', note: '', sources: sources.slice(6) },
          ],
          live_keys: ['reed'],
        });
      }),
    );

    renderSources();

    // Wait for the real payload specifically (not just any text also present in the static
    // fallback, like "Reed") — the fallback renders first while the query is in flight, and a
    // waitFor on a label the fallback also has can resolve during that transient state.
    await waitFor(() => expect(screen.getByText('LinkedIn')).toBeInTheDocument());
    expect(screen.queryByText(/built-in catalogue/i)).not.toBeInTheDocument();
    expect(screen.getByText('Reed')).toBeInTheDocument();
    expect(screen.getByText('Adzuna')).toBeInTheDocument();
    expect(screen.getByText('Exa')).toBeInTheDocument();
    expect(screen.getByText('Civil Service Jobs')).toBeInTheDocument();
    expect(screen.getByText('Some Board')).toBeInTheDocument();
    expect(screen.getByText('Acme')).toBeInTheDocument();
    expect(screen.getByText(/7 enabled|of 7/i)).toBeInTheDocument();
  });

  it('falls back to the built-in catalogue when the endpoint is unreachable, without crashing', async () => {
    server.use(http.get('/api/v1/sources/', () => HttpResponse.error()));

    renderSources();

    await waitFor(() => expect(screen.getByText(/built-in catalogue/i)).toBeInTheDocument());
    expect(screen.getByText('Sources')).toBeInTheDocument();
  });

  // Regression test for the actual "I can't open it" report: this page used to read on/off
  // state from `useDiscoveryStore` — a separate, client-only, per-device store that starts
  // empty — instead of the operator's real, backend-stored `platforms_enabled`. So a real
  // account with sources genuinely enabled saw every single one marked "Disabled" and a
  // "0 of N enabled" count the moment they opened this screen on any device, even though the
  // background worker was actually using them correctly the whole time.
  it('reflects the real backend platforms_enabled, not the separate client-only discovery store', async () => {
    useDiscoveryStore.setState({ enabledSources: [] }); // deliberately empty — must not matter
    server.use(
      http.get('/api/v1/sources/', () => HttpResponse.json(CATALOGUE_RESPONSE)),
      http.get('/api/v1/settings/', () =>
        HttpResponse.json({ platforms_enabled: ['reed'], candidate_profile: {}, role_targets: [] }),
      ),
    );

    renderSources();

    await waitFor(() => expect(screen.getByText('1/2 ON')).toBeInTheDocument());
    expect(screen.getByText('1 of 2 enabled · 2 can return results right now.')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Toggle Reed' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('switch', { name: 'Toggle Adzuna' })).toHaveAttribute('aria-checked', 'false');
  });

  it('treats an empty platforms_enabled as every source on, matching the discovery worker convention', async () => {
    server.use(
      http.get('/api/v1/sources/', () => HttpResponse.json(CATALOGUE_RESPONSE)),
      http.get('/api/v1/settings/', () =>
        HttpResponse.json({ platforms_enabled: [], candidate_profile: {}, role_targets: [] }),
      ),
    );

    renderSources();

    await waitFor(() => expect(screen.getByText('2/2 ON')).toBeInTheDocument());
    expect(screen.getByRole('switch', { name: 'Toggle Reed' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('switch', { name: 'Toggle Adzuna' })).toHaveAttribute('aria-checked', 'true');
  });

  it('toggling a source PUTs the real explicit list to the backend', async () => {
    let putBody: { platforms_enabled?: string[] } | null = null;
    server.use(
      http.get('/api/v1/sources/', () => HttpResponse.json(CATALOGUE_RESPONSE)),
      http.get('/api/v1/settings/', () =>
        HttpResponse.json({ platforms_enabled: ['reed'], candidate_profile: {}, role_targets: [] }),
      ),
      http.put('/api/v1/settings/', async ({ request }) => {
        putBody = (await request.json()) as { platforms_enabled?: string[] };
        return HttpResponse.json({ platforms_enabled: putBody.platforms_enabled, candidate_profile: {}, role_targets: [] });
      }),
    );

    renderSources();
    await waitFor(() => expect(screen.getByText('1/2 ON')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('switch', { name: 'Toggle Adzuna' }));

    await waitFor(() => expect(putBody).not.toBeNull());
    expect(putBody!.platforms_enabled).toEqual(['reed', 'adzuna']);
  });
});
