import { describe, it, expect } from 'vitest';
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

function renderPage(initialPath = '/applications') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <ApplicationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ApplicationsPage — merged Active / Needs action / History', () => {
  it('defaults to the Active tab and shows an in-flight application as a timeline card', async () => {
    server.use(http.get('/api/v1/applications/', () =>
      HttpResponse.json(listOf(app({ id: 'a1', status: 'applying', job_title: 'Live PM Role' })))));
    renderPage();

    expect(await screen.findByText('Live PM Role')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^active/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('Needs action tab shows pending_review applications with an Approve action', async () => {
    server.use(http.get('/api/v1/applications/', () =>
      HttpResponse.json(listOf(app({ id: 'a2', status: 'pending_review', job_title: 'Staged Role' })))));
    renderPage();

    await userEvent.click(screen.getByRole('tab', { name: /needs action/i }));
    expect(await screen.findByText('Staged Role')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument();
  });

  it('History tab shows settled applications in the table view, not the card view', async () => {
    server.use(http.get('/api/v1/applications/', () =>
      HttpResponse.json(listOf(app({ id: 'a3', status: 'rejected', job_title: 'Closed Role' })))));
    renderPage();

    await userEvent.click(screen.getByRole('tab', { name: /^history/i }));
    expect(await screen.findByText('Closed Role')).toBeInTheDocument();
    // The table view renders a "Role" column header the card view does not.
    expect(screen.getByRole('columnheader', { name: 'Role' })).toBeInTheDocument();
  });

  it('History sub-tabs filter within the settled set', async () => {
    server.use(http.get('/api/v1/applications/', () =>
      HttpResponse.json(listOf(
        app({ id: 'a4', status: 'rejected', job_title: 'Rejected Role' }),
        app({ id: 'a5', status: 'offer', job_title: 'Offer Role' }),
      ))));
    renderPage();

    await userEvent.click(screen.getByRole('tab', { name: /^history/i }));
    expect(await screen.findByText('Rejected Role')).toBeInTheDocument();
    expect(screen.getByText('Offer Role')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /^offer$/i }));
    expect(screen.getByText('Offer Role')).toBeInTheDocument();
    expect(screen.queryByText('Rejected Role')).not.toBeInTheDocument();
  });

  it('deep-links straight into a filtered History sub-tab via the URL', async () => {
    // The sub-tab used to be local component state, reset to "all" on every mount — a link
    // from elsewhere (e.g. the dashboard's "Interviews" KPI) landed on History but showed
    // every settled application, not just interviews. It must now come from the URL itself.
    server.use(http.get('/api/v1/applications/', () =>
      HttpResponse.json(listOf(
        app({ id: 'a6', status: 'interview', job_title: 'Interview Role' }),
        app({ id: 'a7', status: 'offer', job_title: 'Offer Role Two' }),
      ))));
    renderPage('/applications?tab=history&sub=interview');

    expect(await screen.findByText('Interview Role')).toBeInTheDocument();
    expect(screen.queryByText('Offer Role Two')).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^interview$/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('an application never appears in more than one of the three views', async () => {
    server.use(http.get('/api/v1/applications/', () =>
      HttpResponse.json(listOf(
        app({ id: 'a1', status: 'applying', job_title: 'Active Role' }),
        app({ id: 'a2', status: 'pending_review', job_title: 'Pending Role' }),
        app({ id: 'a3', status: 'applied', job_title: 'Settled Role' }),
      ))));
    renderPage();

    expect(await screen.findByText('Active Role')).toBeInTheDocument();
    expect(screen.queryByText('Pending Role')).not.toBeInTheDocument();
    expect(screen.queryByText('Settled Role')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /needs action/i }));
    expect(await screen.findByText('Pending Role')).toBeInTheDocument();
    expect(screen.queryByText('Active Role')).not.toBeInTheDocument();
    expect(screen.queryByText('Settled Role')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /^history/i }));
    expect(await screen.findByText('Settled Role')).toBeInTheDocument();
    expect(screen.queryByText('Active Role')).not.toBeInTheDocument();
    expect(screen.queryByText('Pending Role')).not.toBeInTheDocument();
  });

  it('opens directly on the Needs action tab via ?tab=needs_action (Dashboard deep link)', async () => {
    server.use(http.get('/api/v1/applications/', () =>
      HttpResponse.json(listOf(app({ id: 'a2', status: 'pending_review', job_title: 'Staged Role' })))));
    renderPage('/applications?tab=needs_action');

    expect(await screen.findByText('Staged Role')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /needs action/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('shows an empty state on Active with no in-flight applications', async () => {
    server.use(http.get('/api/v1/applications/', () => HttpResponse.json(listOf())));
    renderPage();
    expect(await screen.findByText('No run in progress')).toBeInTheDocument();
  });
});
