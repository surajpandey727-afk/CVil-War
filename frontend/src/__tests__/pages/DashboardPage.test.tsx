import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import DashboardPage from '@/pages/DashboardPage';

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location-probe">{loc.pathname}{loc.search}</div>;
}

function dashStats(overrides: Record<string, unknown> = {}) {
  return {
    total_jobs_found: 40, total_applications: 128, applications_pending: 3, applications_applied: 86,
    applications_interview: 11, applications_rejected: 8, applications_offer: 2, avg_ats_score: 0.82, total_llm_cost_usd: 14.62,
    ...overrides,
  };
}
function app(overrides: Record<string, unknown> = {}) {
  return {
    id: 'a1', job_id: 'j1', job_title: 'Senior Product Manager', company: 'Northwind Labs',
    resume_id: 'r1', status: 'applied', apply_mode: 'review', ats_score: 0.88, cover_letter_path: null,
    applied_at: '2026-07-08T10:00:00Z', response_date: null, notes: null,
    created_at: '2026-07-06T09:00:00Z', updated_at: '2026-07-08T10:00:00Z', ...overrides,
  };
}
const listOf = (...items: object[]) => ({ items, total: items.length, page: 1, page_size: 20, has_next: false });

function renderDash() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DashboardPage live-now card', () => {
  it('shows a Live now card for an in-flight (applying) application', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats())));
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf(app({ status: 'applying', job_title: 'Live PM Role' })))));
    renderDash();
    expect(await screen.findByText(/live now/i)).toBeInTheDocument();
    expect(screen.getAllByText('Live PM Role').length).toBeGreaterThan(0);
  });

  it('does not show a Live now card when nothing is in flight', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats())));
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf(app({ status: 'applied' })))));
    renderDash();
    // The pipeline section is a read-only KPI summary, not a row-level table (that view
    // lives at /applications now) — assert on the count breakdown rendering, not a job title.
    await screen.findByText('Application pipeline');
    expect(screen.queryByText(/live now/i)).not.toBeInTheDocument();
  });
});

describe('DashboardPage greeting pluralization (BUG-006)', () => {
  it('says "1 role" (singular) when exactly one application has been sent', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats({ applications_applied: 1 }))));
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf(app()))));
    renderDash();
    expect(await screen.findByText('1 role')).toBeInTheDocument();
    expect(screen.queryByText('1 roles')).not.toBeInTheDocument();
  });

  it('says "N roles" (plural) for more than one', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats({ applications_applied: 86 }))));
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf(app()))));
    renderDash();
    expect(await screen.findByText('86 roles')).toBeInTheDocument();
  });
});

describe('DashboardPage new observability KPIs', () => {
  it('shows jobs-found-today, unique-jobs, sponsor-confirmed, and CVs-generated', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats({
      jobs_found_today: 12, unique_jobs: 340, sponsor_confirmed_jobs: 27, cvs_generated: 9,
    }))));
    renderDash();
    // The label renders before the query resolves; wait on a value instead so this
    // actually asserts on loaded data, not just the always-present static label.
    expect(await screen.findByText('12')).toBeInTheDocument();
    expect(screen.getByText('Jobs found today')).toBeInTheDocument();
    expect(screen.getByText('Unique jobs')).toBeInTheDocument();
    expect(screen.getByText('340')).toBeInTheDocument();
    expect(screen.getByText('Sponsor confirmed')).toBeInTheDocument();
    expect(screen.getByText('27')).toBeInTheDocument();
    expect(screen.getByText('CVs generated')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
  });
});

describe('DashboardPage KPI and pipeline navigation', () => {
  it('clicking the Interviews KPI goes to the History tab filtered to interview', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats())));
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf(app()))));
    renderDash();

    await userEvent.click(await screen.findByText('Interviews'));

    expect(await screen.findByTestId('location-probe')).toHaveTextContent(
      '/applications?tab=history&sub=interview',
    );
  });

  it('clicking the Applied KPI goes to the History tab filtered to applied', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats())));
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf(app()))));
    renderDash();

    await userEvent.click(await screen.findByText('Applied'));

    expect(await screen.findByTestId('location-probe')).toHaveTextContent(
      '/applications?tab=history&sub=applied',
    );
  });

  it('clicking the Interview pipeline-breakdown cell goes to the same filtered History view', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats())));
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf(
      app({ id: 'a2', status: 'interview' }),
    ))));
    renderDash();

    // The KPI card above is labelled "Interviews" (plural); anchor on the singular pipeline
    // cell label ("Interview" + count) so the two buttons cannot be confused for each other.
    const cell = await screen.findByRole('button', { name: /^Interview\s/i });
    await userEvent.click(cell);

    expect(await screen.findByTestId('location-probe')).toHaveTextContent(
      '/applications?tab=history&sub=interview',
    );
  });

  it('clicking the Needs review pipeline-breakdown cell still goes to needs_action', async () => {
    server.use(http.get('/api/v1/analytics/dashboard', () => HttpResponse.json(dashStats())));
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf(
      app({ id: 'a3', status: 'pending_review' }),
    ))));
    renderDash();

    const cell = await screen.findByRole('button', { name: /needs review/i });
    await userEvent.click(cell);

    expect(await screen.findByTestId('location-probe')).toHaveTextContent(
      '/applications?tab=needs_action',
    );
  });
});
