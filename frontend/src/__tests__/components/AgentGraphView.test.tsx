import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { server } from '@/__tests__/mocks/server';
import AgentGraphView from '@/components/agents/AgentGraphView';

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const NODE_TEMPLATE = ['discovery', 'eligibility', 'scoring', 'application', 'tracking'].map((agent_name) => ({
  agent_name, status: null, last_run: null,
}));

describe('AgentGraphView', () => {
  it('renders all five agent nodes as idle when nothing has ever run', async () => {
    render(<AgentGraphView />, { wrapper: wrapper() });

    expect(await screen.findByText('No agent runs match this filter yet.')).toBeInTheDocument();
    expect(screen.getByText('Discovery')).toBeInTheDocument();
    expect(screen.getByText('Eligibility')).toBeInTheDocument();
    expect(screen.getByText('Scoring')).toBeInTheDocument();
    expect(screen.getByText('Application')).toBeInTheDocument();
    expect(screen.getByText('Tracking')).toBeInTheDocument();
    expect(screen.getAllByText('Idle')).toHaveLength(5);
  });

  it('shows a node status and its most recent run summary', async () => {
    server.use(
      http.get('/api/v1/agent-runs/', () =>
        HttpResponse.json({
          items: [
            {
              id: 'run-1', agent_name: 'eligibility', status: 'done',
              started_at: '2026-08-29T00:00:00Z', finished_at: '2026-08-29T00:00:01Z',
              input_summary: 'Re-classify sponsorship for job job-1',
              output_summary: 'keyword_detected: Posting states: "sponsorship"',
              error: null, linked_entity_type: 'job', linked_entity_id: 'job-1',
            },
          ],
          total: 1,
          nodes: NODE_TEMPLATE.map((n) =>
            n.agent_name === 'eligibility'
              ? { ...n, status: 'done', last_run: {
                  id: 'run-1', agent_name: 'eligibility', status: 'done',
                  started_at: '2026-08-29T00:00:00Z', finished_at: '2026-08-29T00:00:01Z',
                  input_summary: 'Re-classify sponsorship for job job-1',
                  output_summary: 'keyword_detected: Posting states: "sponsorship"',
                  error: null, linked_entity_type: 'job', linked_entity_id: 'job-1',
                } }
              : n,
          ),
        }),
      ),
    );

    render(<AgentGraphView />, { wrapper: wrapper() });

    expect(await screen.findAllByText(/keyword_detected/)).toHaveLength(2); // node card + log row
    expect(screen.getAllByText('Done')).toHaveLength(3); // filter chip + node badge + log row
  });

  it('filters the log by agent when a node is clicked', async () => {
    server.use(
      http.get('/api/v1/agent-runs/', ({ request }) => {
        const url = new URL(request.url);
        const agentName = url.searchParams.get('agent_name');
        const items = agentName === 'scoring'
          ? [{
              id: 'run-2', agent_name: 'scoring', status: 'done',
              started_at: '2026-08-29T00:00:00Z', finished_at: '2026-08-29T00:00:01Z',
              input_summary: null, output_summary: 'Recommend best résumé', error: null,
              linked_entity_type: 'job', linked_entity_id: 'job-1',
            }]
          : [];
        return HttpResponse.json({ items, total: items.length, nodes: NODE_TEMPLATE });
      }),
    );

    render(<AgentGraphView />, { wrapper: wrapper() });
    await screen.findByText('No agent runs match this filter yet.');

    await userEvent.click(screen.getByText('Scoring'));

    await waitFor(() => expect(screen.getByText('Recommend best résumé')).toBeInTheDocument());
  });
});
