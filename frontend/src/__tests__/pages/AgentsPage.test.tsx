import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import AgentsPage from '@/pages/AgentsPage';
import type { AgentCard, AgentRosterResponse } from '@/types/assistant';

function agent(over: Partial<AgentCard> & Pick<AgentCard, 'key' | 'name'>): AgentCard {
  return {
    description: `${over.name} does its job.`,
    status: 'idle',
    status_text: 'Ready.',
    last_run: null,
    tracks_runs: true,
    counts: [],
    actions: [],
    section: { label: 'Jobs', kind: 'link', to: '/jobs', action: null },
    ...over,
  };
}

const ROSTER: AgentRosterResponse = {
  assistant_available: false,
  agents: [
    agent({
      key: 'discovery',
      name: 'Discovery',
      status_text: 'No background scheduler on this deployment; it runs when you trigger it.',
      counts: [{ label: 'New UK jobs (24h)', value: 12 }, { label: 'Active role targets', value: 2 }],
      last_run: { status: 'done', started_at: new Date().toISOString(), finished_at: null, summary: '12 job(s) found', error: null },
      actions: [
        { label: 'Run discovery now', kind: 'confirm', to: null, action: 'run_discovery_now' },
        { label: 'Role targets', kind: 'link', to: '/targets', action: null },
      ],
    }),
    agent({
      key: 'tracking',
      name: 'Tracking',
      status: 'needs_attention',
      status_text: "Gmail isn't connected yet. Connect it in Communications.",
      section: { label: 'Communications', kind: 'link', to: '/communications', action: null },
      last_run: { status: 'error', started_at: new Date().toISOString(), finished_at: null, summary: null, error: 'token expired' },
    }),
    agent({
      key: 'assistant',
      name: 'Assistant',
      status: 'off',
      status_text: "Off: ANTHROPIC_API_KEY isn't set on this deployment.",
      tracks_runs: false,
      section: { label: 'Assistant', kind: 'link', to: '/assistant', action: null },
    }),
  ],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/agents']}><AgentsPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

const card = (name: string) => screen.getByRole('article', { name });

describe('AgentsPage', () => {
  it('renders each agent with status, counts, last run and its section link', async () => {
    server.use(http.get('/api/v1/assistant/agents', () => HttpResponse.json(ROSTER)));
    renderPage();
    await screen.findByRole('heading', { name: 'Discovery' });

    const discovery = card('Discovery');
    expect(within(discovery).getByText('Idle')).toBeInTheDocument();
    expect(within(discovery).getByText('New UK jobs (24h)')).toBeInTheDocument();
    expect(within(discovery).getByText('12')).toBeInTheDocument();
    expect(within(discovery).getByText(/Last run just now · done · 12 job\(s\) found/)).toBeInTheDocument();
    expect(within(discovery).getByRole('link', { name: /Open Jobs/ })).toHaveAttribute('href', '/jobs');
    expect(within(discovery).getByRole('link', { name: 'Role targets' })).toHaveAttribute('href', '/targets');

    const tracking = card('Tracking');
    expect(within(tracking).getByText('Needs attention')).toBeInTheDocument();
    expect(within(tracking).getByText('token expired')).toBeInTheDocument();
    expect(within(tracking).getByRole('link', { name: /Open Communications/ })).toHaveAttribute('href', '/communications');

    const assistant = card('Assistant');
    expect(within(assistant).getByText('Off')).toBeInTheDocument();
    expect(within(assistant).getByText(/no run log/)).toBeInTheDocument();
    expect(screen.getByText(/The Assistant is off on this deployment/)).toBeInTheDocument();
    expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent('3 agents, 1 need attention.');
  });

  it('runs discovery only after confirmation', async () => {
    const confirmed: string[] = [];
    server.use(
      http.get('/api/v1/assistant/agents', () => HttpResponse.json(ROSTER)),
      http.post('/api/v1/assistant/prepare', () =>
        HttpResponse.json({ ok: true, pending: { token: 'disc-tok', summary: 'Run discovery now for 2 role target(s).' }, message: '' })),
      http.post('/api/v1/assistant/confirm', async ({ request }) => {
        confirmed.push(((await request.json()) as { token: string }).token);
        return HttpResponse.json({ ok: true, message: 'Discovery finished: 5 job(s) found.' });
      }),
    );
    renderPage();
    await screen.findByRole('heading', { name: 'Discovery' });

    await userEvent.click(within(card('Discovery')).getByRole('button', { name: 'Run discovery now' }));
    const confirm = await within(card('Discovery')).findByRole('group', { name: 'Action awaiting confirmation' });
    expect(within(confirm).getByText(/Run discovery now for 2 role target/)).toBeInTheDocument();
    expect(confirmed).toEqual([]);

    await userEvent.click(within(confirm).getByRole('button', { name: 'Confirm' }));
    expect(await within(confirm).findByText('Discovery finished: 5 job(s) found.')).toBeInTheDocument();
    expect(confirmed).toEqual(['disc-tok']);
  });

  it('shows why an action is unavailable', async () => {
    server.use(
      http.get('/api/v1/assistant/agents', () => HttpResponse.json(ROSTER)),
      http.post('/api/v1/assistant/prepare', () =>
        HttpResponse.json({ ok: false, pending: null, message: 'No active role targets to search for.' })),
    );
    renderPage();
    await screen.findByRole('heading', { name: 'Discovery' });
    await userEvent.click(within(card('Discovery')).getByRole('button', { name: 'Run discovery now' }));
    expect(await within(card('Discovery')).findByText('No active role targets to search for.')).toBeInTheDocument();
  });

  it('shows a load error', async () => {
    server.use(http.get('/api/v1/assistant/agents', () => HttpResponse.json({ detail: 'Server unavailable' }, { status: 500 })));
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent('Server unavailable');
  });
});
