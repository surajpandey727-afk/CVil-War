import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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

  it('says which rows need a sign-in and which can go out without one', async () => {
    const linkedin = {
      key: 'linkedin', label: 'LinkedIn', tier: 'tier1', health: 'live', implemented: true,
      needs_credential: false, capabilities: [], enabled: true, connected: false,
      connection_state: 'not_connected', account: null, last_used_at: null, expires_at: null,
      detail: null, last_error: null,
      actions: [{ key: 'connect', label: 'Connect', available: true, reason: '' }],
    };
    server.use(
      http.get('/api/v1/applications/', () =>
        HttpResponse.json(listOf(
          app({ id: 'p1', status: 'pending_review', job_title: 'LinkedIn Role', resume_id: 'r1', portal: 'linkedin', application_url: 'https://www.linkedin.com/jobs/view/1/' }),
          app({ id: 'p2', status: 'pending_review', job_title: 'Careers Role', resume_id: 'r1', portal: 'careers:monzo', application_url: 'https://boards.greenhouse.io/monzo/jobs/1' }),
        ))),
      http.get('/api/v1/settings/platforms', () =>
        HttpResponse.json({ platforms: [linkedin], total: 1, usable: 1, connected: 0 })),
    );
    renderPage('/applications?tab=needs_action');

    expect(await screen.findByText('LinkedIn Role')).toBeInTheDocument();
    // The banner separates finding jobs from submitting them, and counts each blocker.
    expect(await screen.findByText(/Your sources find jobs; they never submit anything/)).toBeInTheDocument();
    expect(screen.getByText(/1 go through LinkedIn and need your LinkedIn sign-in/)).toBeInTheDocument();
    expect(screen.getByText(/1 need no sign-in/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect LinkedIn' })).toBeInTheDocument();
    // Each row says its own next step and always offers a way forward.
    expect(screen.getByText('Waiting for your approval — then your LinkedIn sign-in')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'I applied myself' })).toHaveLength(2);
    expect(screen.getAllByRole('link', { name: /Open posting/ })[1]).toHaveAttribute('href', 'https://boards.greenhouse.io/monzo/jobs/1');
  });

  it('tells an approved row it is waiting for the automation host, not for nothing', async () => {
    server.use(
      http.get('/api/v1/applications/', () =>
        HttpResponse.json(listOf(app({ id: 'a1', status: 'approved', job_title: 'Data Scientist', resume_id: 'r1', portal: 'careers:monzo', approved: true })))),
      http.get('/api/v1/settings/platforms', () =>
        HttpResponse.json({ platforms: [], total: 0, usable: 0, connected: 0 })),
    );
    renderPage('/applications');

    expect(await screen.findByText('Data Scientist')).toBeInTheDocument();
    expect(await screen.findByText('Approved — waiting for the automation host on your PC')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy start command' })).toBeInTheDocument();
  });

  it('records "I applied myself" as a manual application', async () => {
    const puts: unknown[] = [];
    server.use(
      http.get('/api/v1/applications/', () =>
        HttpResponse.json(listOf(app({ id: 'm1', status: 'pending_review', job_title: 'Manual Role', resume_id: 'r1' })))),
      http.get('/api/v1/settings/platforms', () =>
        HttpResponse.json({ platforms: [], total: 0, usable: 0, connected: 0 })),
      http.put('/api/v1/applications/m1/status', async ({ request }) => {
        puts.push(await request.json());
        return HttpResponse.json(app({ id: 'm1', status: 'applied', job_title: 'Manual Role' }));
      }),
    );
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage('/applications?tab=needs_action');

    await userEvent.click(await screen.findByRole('button', { name: 'I applied myself' }));
    await waitFor(() => expect(puts).toEqual([{ status: 'applied' }]));
    confirm.mockRestore();
  });

  it('marks an applied-but-unconfirmed application honestly, and a simulated one, but not a confirmed one', async () => {
    server.use(http.get('/api/v1/applications/', () =>
      HttpResponse.json(listOf(
        app({ id: 'u1', status: 'applied', confirmation_state: 'unconfirmed', job_title: 'Unconfirmed Role' }),
        app({ id: 's1', status: 'applied', confirmation_state: 'simulated', job_title: 'Simulated Role' }),
        app({ id: 'c1', status: 'applied', confirmation_state: 'confirmed', job_title: 'Confirmed Role' }),
      ))));
    renderPage();

    await userEvent.click(screen.getByRole('tab', { name: /^history/i }));
    expect(await screen.findByText('Unconfirmed Role')).toBeInTheDocument();
    expect(screen.getByText('Unconfirmed')).toBeInTheDocument();
    expect(screen.getByText('Simulated')).toBeInTheDocument();
    // A genuinely confirmed application carries no caveat badge.
    expect(screen.queryByText('Not confirmed')).not.toBeInTheDocument();
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

describe('ApplicationsPage dead ends (sweep)', () => {
  it('resumes a CAPTCHA-paused row in a visible window', async () => {
    const posts: string[] = [];
    server.use(
      http.get('/api/v1/applications/', () =>
        HttpResponse.json(listOf(app({ id: 'c1', status: 'pending_review', job_title: 'Paused Role', resume_id: 'r1', portal: 'reed', blocked_reason: 'captcha' })))),
      http.get('/api/v1/settings/platforms', () => HttpResponse.json({ platforms: [], total: 0, usable: 0, connected: 0 })),
      http.post('/api/v1/applications/c1/resolve-blocker', () => { posts.push('c1'); return HttpResponse.json({ queued: true }); }),
    );
    renderPage('/applications?tab=needs_action');

    expect(await screen.findByText(/asked for a human check/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Resume in a visible window' }));
    await waitFor(() => expect(posts).toEqual(['c1']));
  });

  it('"Approve all" never releases a row with no résumé', async () => {
    let approved: string[] = [];
    server.use(
      http.get('/api/v1/applications/', () =>
        HttpResponse.json(listOf(
          app({ id: 'w1', status: 'pending_review', job_title: 'With CV', resume_id: 'r1' }),
          app({ id: 'n1', status: 'pending_review', job_title: 'No CV', resume_id: null }),
        ))),
      http.get('/api/v1/settings/platforms', () => HttpResponse.json({ platforms: [], total: 0, usable: 0, connected: 0 })),
      http.post('/api/v1/applications/bulk-approve', async ({ request }) => {
        approved = ((await request.json()) as { application_ids: string[] }).application_ids;
        return HttpResponse.json({ approved: approved.length });
      }),
    );
    renderPage('/applications?tab=needs_action');

    await userEvent.click(await screen.findByRole('button', { name: /Approve all/ }));
    await waitFor(() => expect(approved).toEqual(['w1']));
  });

  it('loads applications past the first page of 100', async () => {
    server.use(
      http.get('/api/v1/applications/', ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('page'));
        return HttpResponse.json({
          items: [app({ id: `p${page}`, status: 'queued', job_title: `Role page ${page}` })],
          total: 2, page, page_size: 100, has_next: page === 1,
        });
      }),
      http.get('/api/v1/settings/platforms', () => HttpResponse.json({ platforms: [], total: 0, usable: 0, connected: 0 })),
    );
    renderPage('/applications');

    expect(await screen.findByText('Role page 2')).toBeInTheDocument();
    expect(screen.getByText('Role page 1')).toBeInTheDocument();
  });
});
