/**
 * The sidebar's agent indicator says what is really happening. It used to pulse "Agent active"
 * permanently, including when no worker was running at all.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import Sidebar from '@/components/layout/Sidebar';

function renderWith(stats: Record<string, number>) {
  server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json({
    total_jobs_found: 0, total_applications: 0, applications_pending: 0, applications_applied: 0,
    applications_interview: 0, applications_rejected: 0, applications_offer: 0, avg_ats_score: 0,
    total_llm_cost_usd: 0, applications_queued: 0, applications_applying: 0, applications_approved: 0,
    ...stats,
  })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Sidebar /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Sidebar agent indicator', () => {
  it('says idle when nothing is waiting', async () => {
    renderWith({});
    expect(await screen.findByText('Agent idle')).toBeInTheDocument();
    expect(screen.queryByText('Agent active')).toBeNull();
  });

  it('counts what is waiting for the automation host', async () => {
    renderWith({ applications_approved: 2, applications_queued: 1 });
    expect(await screen.findByText('3 waiting to send')).toBeInTheDocument();
  });

  it('says it is applying only while something is in flight', async () => {
    renderWith({ applications_applying: 1 });
    expect(await screen.findByText('Applying to 1 now')).toBeInTheDocument();
  });
});
