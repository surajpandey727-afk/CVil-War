import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import ActionQueue from '@/components/dashboard/ActionQueue';

function item(overrides: Record<string, unknown> = {}) {
  return {
    application_id: 'a1',
    job_id: 'j1',
    title: 'Senior Product Manager',
    company: 'Northwind',
    action: 'complete_assessment',
    priority: 'high',
    reason: 'Assessment due in 3 hours.',
    score: 78.3,
    due_at: new Date(Date.now() + 3 * 3_600_000).toISOString(),
    health: 'action_required',
    status: 'applied',
    target: 'assessment',
    application_url: null,
    portal: null,
    ...overrides,
  };
}

const queueOf = (...items: object[]) => ({
  items,
  total: items.length,
  by_priority: items.reduce<Record<string, number>>((acc, i) => {
    const p = (i as { priority: string }).priority;
    acc[p] = (acc[p] ?? 0) + 1;
    return acc;
  }, {}),
});

function renderQueue() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/dashboard" element={<ActionQueue />} />
          <Route path="/applications/:id" element={<div>application detail</div>} />
          <Route path="/sources" element={<div>connection centre</div>} />
          <Route path="/resumes" element={<div>document picker</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ActionQueue', () => {
  it('shows the reason verbatim, not just a status', async () => {
    // The whole point of the queue: "Assessment due in 3 hours" is actionable,
    // "APPLIED" is not.
    server.use(http.get('/api/v1/command-centre/queue', () => HttpResponse.json(queueOf(item()))));
    renderQueue();
    expect(await screen.findByText(/Assessment due in 3 hours/)).toBeInTheDocument();
  });

  it('distinguishes an empty queue from a failed one', async () => {
    // Rendering "nothing to do" when the request failed would hide work the user must not
    // miss — the two states mean opposite things.
    server.use(
      http.get('/api/v1/command-centre/queue', () => HttpResponse.json({ items: [], total: 0, by_priority: {} })),
    );
    renderQueue();
    expect(await screen.findByText(/nothing needs you right now/i)).toBeInTheDocument();
  });

  it('reports a load failure instead of claiming there is nothing to do', async () => {
    server.use(
      http.get('/api/v1/command-centre/queue', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    renderQueue();
    expect(await screen.findByText(/could not load your action queue/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing needs you/i)).not.toBeInTheDocument();
  });

  it('routes a session action to the connection centre, not the application', async () => {
    // Each action must land on the surface that actually resolves it; sending a "session
    // expired" item to the application detail page leaves the user to find reconnect
    // themselves, which is the navigation cost the queue exists to remove.
    server.use(
      http.get('/api/v1/command-centre/queue', () =>
        HttpResponse.json(queueOf(item({ action: 'relogin', target: 'connection', priority: 'medium', reason: 'Session expired.' })))),
    );
    renderQueue();
    await userEvent.click(await screen.findByRole('button', { name: /session expired/i }));
    expect(await screen.findByText('connection centre')).toBeInTheDocument();
  });

  it('routes a missing-document action to the document picker', async () => {
    server.use(
      http.get('/api/v1/command-centre/queue', () =>
        HttpResponse.json(queueOf(item({ action: 'upload_cv', target: 'documents', priority: 'medium', reason: 'No CV selected.' })))),
    );
    renderQueue();
    await userEvent.click(await screen.findByRole('button', { name: /cv required/i }));
    expect(await screen.findByText('document picker')).toBeInTheDocument();
  });

  it('surfaces the deadline so urgency is visible without reading the reason', async () => {
    server.use(http.get('/api/v1/command-centre/queue', () => HttpResponse.json(queueOf(item()))));
    renderQueue();
    expect(await screen.findByText(/3h left/i)).toBeInTheDocument();
  });

  it('shows an overdue deadline as overdue rather than a negative duration', async () => {
    server.use(
      http.get('/api/v1/command-centre/queue', () =>
        HttpResponse.json(queueOf(item({ due_at: new Date(Date.now() - 3_600_000).toISOString() })))),
    );
    renderQueue();
    expect(await screen.findByText(/overdue/i)).toBeInTheDocument();
  });
});
