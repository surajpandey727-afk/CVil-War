import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

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

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SettingsPage />
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

  it('renders configured LLM providers', async () => {
    server.use(http.get('/api/v1/settings/', () => HttpResponse.json(settings())));
    server.use(http.get('/api/v1/settings/llm-providers', () => HttpResponse.json([
      { provider: 'openai', configured: true, model: 'gpt-4o', is_primary: true },
      { provider: 'groq', configured: false, model: 'llama-3', is_primary: false },
    ])));
    renderSettings();
    expect(await screen.findByText(/openai/i)).toBeInTheDocument();
    expect(screen.getByText(/groq/i)).toBeInTheDocument();
  });
});
