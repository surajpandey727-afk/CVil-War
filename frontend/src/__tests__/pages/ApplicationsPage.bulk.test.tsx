import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import ApplicationsPage from '@/pages/ApplicationsPage';

function app(overrides: Record<string, unknown> = {}) {
  return {
    id: 'a1', job_id: 'j1', job_title: 'Senior Product Manager', company: 'Northwind Labs',
    resume_id: 'r1', status: 'applied', apply_mode: 'review', ats_score: 0.88, cover_letter_path: null,
    applied_at: '2026-07-08T10:00:00Z', response_date: null, notes: null,
    created_at: '2026-07-06T09:00:00Z', updated_at: '2026-07-08T10:00:00Z', ...overrides,
  };
}
const listOf = (...items: object[]) => ({ items, total: items.length, page: 1, page_size: 100, has_next: false });
const pending = (id: string, title: string, extra: Record<string, unknown> = {}) =>
  app({ id, job_id: `j-${id}`, status: 'pending_review', job_title: title, resume_id: null, ats_score: null, ...extra });

function renderPage(initialPath = '/applications?tab=needs_action') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <ApplicationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function scoreItem(id: string, ats: number | null) {
  return {
    application_id: id, job_id: `j-${id}`, scored: ats != null,
    reason: ats == null ? 'This posting has no description to score against' : '',
    ats_score: ats, persisted: false,
    scored_with: ats == null ? null : { resume_id: 'r-best', resume_name: 'AIPM.pdf', source: 'best' },
    summary: ats == null ? null : {
      ats_match: ats, parsing: 0.97, shortlist: 0.7, band: 'Moderate alignment', shortlist_band: 'Moderate alignment',
      tiers: {}, top_gaps: ['sql'], constrained_by: [], recruiter_signal: 'Mixed', tailoring_limit: '',
    },
  };
}

const tailored = (id: string, before: number, after: number, status = 'generated') => ({
  application: pending(id, 'x', { resume_id: 'rt' }),
  resume: { id: 'rt', name: 'AIPM - tailored', type: 'tailored', ats_score: after },
  ats_before: before, ats_after: after, status, target_note: '', summary: null,
});

describe('Needs action: ATS on every row', () => {
  it('shows a score on every row, and a reason where there cannot be one', async () => {
    server.use(
      http.get('/api/v1/applications/', () =>
        HttpResponse.json(listOf(pending('p1', 'Role One'), pending('p2', 'Role Two'), pending('p3', 'Role Three')))),
      http.post('/api/v1/applications/score', () =>
        HttpResponse.json({ items: [scoreItem('p1', 0.62), scoreItem('p2', 0.48), scoreItem('p3', null)], scored: 2, skipped: 1 })),
    );
    renderPage();

    expect(await screen.findByText('Role One')).toBeInTheDocument();
    await vi.waitFor(() => expect(screen.getByText('ATS 62%')).toBeInTheDocument());
    expect(screen.getByText('ATS 48%')).toBeInTheDocument();
    expect(screen.getByText('No description')).toBeInTheDocument();
    expect(screen.getAllByTestId('ats-chip')).toHaveLength(3);
  });
});

describe('Needs action: bulk tailoring', () => {
  it('tailors a résumé for each selected role and reports the generated file’s own score', async () => {
    const called: string[] = [];
    server.use(
      http.get('/api/v1/applications/', () =>
        HttpResponse.json(listOf(pending('p1', 'Role One'), pending('p2', 'Role Two'), pending('p3', 'Role Three')))),
      http.post('/api/v1/applications/:id/tailor', ({ params }) => {
        called.push(String(params.id));
        return HttpResponse.json(tailored(String(params.id), 0.55, 0.71));
      }),
    );
    renderPage();
    await screen.findByText('Role One');

    await userEvent.click(screen.getByRole('checkbox', { name: /select role one/i }));
    await userEvent.click(screen.getByRole('checkbox', { name: /select role three/i }));
    await userEvent.click(screen.getByRole('button', { name: /tailor résumés for 2/i }));

    await vi.waitFor(() => expect([...called].sort()).toEqual(['p1', 'p3']));
    expect(await screen.findAllByText(/Tailored · ATS 55% → 71%/)).toHaveLength(2);
    expect(await screen.findByText(/2 tailored · 2 with a higher match/)).toBeInTheDocument();
  });

  it('a failure on one role is shown on that row and does not stop the others', async () => {
    server.use(
      http.get('/api/v1/applications/', () => HttpResponse.json(listOf(pending('p1', 'Role One'), pending('p2', 'Role Two')))),
      http.post('/api/v1/applications/:id/tailor', ({ params }) =>
        params.id === 'p1'
          ? HttpResponse.json({ detail: 'This posting has no description, so there is nothing to tailor the résumé to.' }, { status: 422 })
          : HttpResponse.json(tailored('p2', 0.5, 0.6))),
    );
    renderPage();
    await screen.findByText('Role One');
    await userEvent.click(screen.getByRole('button', { name: /select all 2/i }));
    await userEvent.click(screen.getByRole('button', { name: /tailor résumés for 2/i }));

    expect(await screen.findByText(/no description, so there is nothing to tailor/i)).toBeInTheDocument();
    expect(await screen.findByText(/Tailored · ATS 50% → 60%/)).toBeInTheDocument();
    expect(await screen.findByText(/1 tailored · 1 with a higher match · 1 failed/)).toBeInTheDocument();
  });

  it('says so, instead of pretending, when nothing more could be changed', async () => {
    server.use(
      http.get('/api/v1/applications/', () => HttpResponse.json(listOf(pending('p1', 'Role One')))),
      http.post('/api/v1/applications/:id/tailor', () => HttpResponse.json(tailored('p1', 0.5, 0.5, 'unchanged'))),
    );
    renderPage();
    await screen.findByText('Role One');
    await userEvent.click(screen.getByRole('checkbox', { name: /select role one/i }));
    await userEvent.click(screen.getByRole('button', { name: /tailor résumés for 1/i }));
    expect(await screen.findByText(/Kept your résumé as is/)).toBeInTheDocument();
  });

  it('will not approve a selected role that has no résumé attached', async () => {
    let approved: string[] = [];
    server.use(
      http.get('/api/v1/applications/', () =>
        HttpResponse.json(listOf(pending('p1', 'Has Resume', { resume_id: 'rt', ats_score: 0.7 }), pending('p2', 'No Resume')))),
      http.post('/api/v1/applications/bulk-approve', async ({ request }) => {
        approved = ((await request.json()) as { application_ids: string[] }).application_ids;
        return HttpResponse.json({ approved: approved.length });
      }),
    );
    renderPage();
    await screen.findByText('Has Resume');
    await userEvent.click(screen.getByRole('button', { name: /select all 2/i }));
    await userEvent.click(screen.getByRole('button', { name: /approve 2 selected/i }));

    await vi.waitFor(() => expect(approved).toEqual(['p1']));
  });

  it('a second run cannot start while one is in flight', async () => {
    let calls = 0;
    server.use(
      http.get('/api/v1/applications/', () => HttpResponse.json(listOf(pending('p1', 'Role One')))),
      http.post('/api/v1/applications/:id/tailor', async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 150));
        return HttpResponse.json(tailored('p1', 0.5, 0.6));
      }),
    );
    renderPage();
    await screen.findByText('Role One');
    await userEvent.click(screen.getByRole('checkbox', { name: /select role one/i }));
    await userEvent.click(screen.getByRole('button', { name: /tailor résumés for 1/i }));
    // While running, the Tailor button is replaced by Stop, so a double click cannot queue a second run.
    expect(screen.queryByRole('button', { name: /tailor résumés for/i })).not.toBeInTheDocument();
    await vi.waitFor(() => expect(screen.getByText(/1 tailored/)).toBeInTheDocument());
    expect(calls).toBe(1);
  });
});
