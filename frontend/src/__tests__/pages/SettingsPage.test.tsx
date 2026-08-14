import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import SettingsPage from '@/pages/SettingsPage';

function settings(overrides: Record<string, unknown> = {}) {
  return {
    apply_mode: 'review', min_ats_score: 0.75, max_parallel: 3, preferred_provider: 'openai',
    platforms_enabled: ['linkedin', 'indeed'],
    candidate_profile: {
      full_name: 'Alex Morgan', email: 'a@x.com', phone: '', location: '', linkedin_url: '',
      github_url: '', summary: '', skills: [], experience: [], education: [], certifications: [],
    },
    ...overrides,
  };
}

function renderSettings(route = '/settings') {
  // The page reads ?section= to deep-link the platform panel, so it needs a router — the
  // real app always has one.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SettingsPage', () => {
  it('loads the current apply mode', async () => {
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    server.use(http.get('/api/v1/settings/llm-providers', () => HttpResponse.json([])));
    renderSettings();
    const select = (await screen.findByLabelText(/apply mode/i)) as HTMLSelectElement;
    expect(select.value).toBe('review');
  });

  it('saves a changed apply mode via PUT', async () => {
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    server.use(http.get('/api/v1/settings/llm-providers', () => HttpResponse.json([])));
    let body: { apply_mode?: string } | null = null;
    server.use(http.put('/api/v1/settings/', async ({ request }) => {
      body = (await request.json()) as { apply_mode: string };
      return HttpResponse.json(settings({ apply_mode: body!.apply_mode }));
    }));

    renderSettings();
    const select = (await screen.findByLabelText(/apply mode/i)) as HTMLSelectElement;
    await userEvent.selectOptions(select, 'autonomous');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.apply_mode).toBe('autonomous');
  });

  it('shows an error card with a Retry button when settings fail to load', async () => {
    server.use(http.get('/api/v1/settings/', () => new HttpResponse(null, { status: 500 })));
    server.use(http.get('/api/v1/settings/llm-providers', () => HttpResponse.json([])));
    renderSettings();
    expect(await screen.findByText(/couldn't load your settings/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('lists the providers the gateway actually offers', async () => {
    // This used to assert on a hard-coded openai/groq pair with invented model names. The
    // panel now renders whatever the gateway reports, so the assertion is on discovery.
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    renderSettings();

    // The page issues four independent requests now (settings, platforms, catalogue,
    // usage), so wait for the AI section itself before reaching into it — a bare findBy on
    // the provider row races the slowest of the four under suite load.
    await screen.findByText('AI providers & models', undefined, { timeout: 5000 });

    // Each provider is an expandable row; the usage breakdown names them again, which is
    // correct — the same provider appears as something the gateway offers and as something
    // tokens were spent on. Targeting the button disambiguates without hiding that.
    expect(
      await screen.findByRole('button', { name: /combo 2 models/i }, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /groq 1 model/i })).toBeInTheDocument();
    expect(screen.getByText(/3 models across 2 providers/)).toBeInTheDocument();
    expect(screen.getByText('openai/Full-Send')).toBeInTheDocument();
  });

  it('flags a default model the gateway does not offer', async () => {
    // A default naming a model that cannot be routed is a real misconfiguration that
    // otherwise only surfaces much later as a failed run.
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    server.use(
      http.get('/api/v1/settings/ai/catalogue', () =>
        HttpResponse.json({
          reachable: true, error: null, base_url: 'http://localhost:20128/v1',
          provider_count: 1, model_count: 1, default_model: 'openai/gpt-4o',
          default_model_available: false,
          providers: [{ id: 'combo', model_count: 1, models: [
            { id: 'Full-Send', provider: 'combo', capabilities: [], context_length: null, max_input_tokens: null, max_output_tokens: null, is_default: false },
          ] }],
        }),
      ),
    );
    renderSettings();

    expect(await screen.findByText(/not offered by this gateway/i)).toBeInTheDocument();
  });

  it('says the gateway is unreachable rather than showing an empty provider list', async () => {
    // "Cannot reach the gateway" and "the gateway offers nothing" are different problems.
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    server.use(
      http.get('/api/v1/settings/ai/catalogue', () =>
        HttpResponse.json({
          reachable: false, error: 'ConnectError: connection refused',
          base_url: 'http://localhost:20128/v1', provider_count: 0, model_count: 0,
          default_model: 'openai/Full-Send', default_model_available: false, providers: [],
        }),
      ),
    );
    renderSettings();

    expect(await screen.findByText(/gateway unreachable/i)).toBeInTheDocument();
    expect(screen.getByText(/connection refused/i)).toBeInTheDocument();
  });

  it('shows recorded token usage', async () => {
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    renderSettings();

    // 1.24M is the headline total and also the model/task/provider breakdown value, since
    // one model accounted for all of it.
    expect((await screen.findAllByText('1.24M')).length).toBeGreaterThan(0);
    expect(screen.getByText('820.0K')).toBeInTheDocument();
    expect(screen.getByText('420.0K')).toBeInTheDocument();
  });

  it('says no calls were recorded rather than showing zeroes', async () => {
    // A row of confident zeroes reads as "measured, and it was nothing".
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    server.use(
      http.get('/api/v1/settings/ai/usage', () =>
        HttpResponse.json({
          period: '7d', recorded: false, requests: 0, errors: 0, prompt_tokens: 0,
          completion_tokens: 0, total_tokens: 0, cost_usd: 0, by_provider: [],
          by_model: [], by_purpose: [], top_model: null, top_purpose: null,
        }),
      ),
    );
    renderSettings();

    expect(await screen.findByText(/no llm calls recorded in this period/i)).toBeInTheDocument();
  });

  it('renders the platform manager from the registry', async () => {
    // Settings hard-coded four platforms while the registry served fifty-five, so the two
    // screens disagreed about what the product supports. Detail is covered against the
    // panel itself in PlatformsPanel.test.tsx.
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    renderSettings();

    expect(await screen.findByText('Remotive')).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 sources have a working adapter/)).toBeInTheDocument();
  });

  it('deep-links to the platform section from Sources', async () => {
    // "Manage" used to land on /settings with no indication of where to look.
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    renderSettings('/settings?section=platforms');

    expect(await screen.findByText('Platforms')).toBeInTheDocument();
  });
});
