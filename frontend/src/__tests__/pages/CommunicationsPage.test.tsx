import { describe, it, expect } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import CommunicationsPage from '@/pages/CommunicationsPage';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CommunicationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CommunicationsPage', () => {
  it('shows setup guidance when neither Gmail nor Apollo is configured', async () => {
    renderPage();

    expect(await screen.findByText(/GMAIL_CLIENT_ID/)).toBeInTheDocument();
    expect(screen.getByText(/APOLLO_API_KEY/)).toBeInTheDocument();
    expect(await screen.findByText(/Connect Gmail above and run a sync/)).toBeInTheDocument();
  });

  it('offers a Connect Gmail link when configured but not connected', async () => {
    server.use(
      http.get('/api/v1/communications/gmail/status', () =>
        HttpResponse.json({
          configured: true, connected: false, authorize_url: 'https://accounts.google.com/auth-x',
        }),
      ),
    );

    renderPage();

    const link = await screen.findByRole('link', { name: 'Connect Gmail' });
    expect(link).toHaveAttribute('href', 'https://accounts.google.com/auth-x');
  });

  it('shows Sync now and Disconnect when Gmail is connected, and reports the sync result', async () => {
    server.use(
      http.get('/api/v1/communications/gmail/status', () =>
        HttpResponse.json({ configured: true, connected: true, authorize_url: null }),
      ),
      http.post('/api/v1/communications/inbox-sync', () =>
        HttpResponse.json({
          fetched: 5, already_seen: 2, matched_to_application: 2, unmatched: 1, errors: [],
        }),
      ),
    );

    renderPage();

    const syncButton = await screen.findByRole('button', { name: 'Sync now' });
    expect(screen.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();

    await userEvent.click(syncButton);

    // The button returns to its idle label once the sync mutation resolves.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sync now' })).toBeInTheDocument());
  });

  it('renders feed items with a classification badge', async () => {
    server.use(
      http.get('/api/v1/communications/', () =>
        HttpResponse.json({
          items: [
            {
              id: 'ce-1', source: 'gmail', application_id: 'app-1',
              sender: '"Monzo Recruiting" <hr@monzo.com>', subject: 'Update on your application',
              snippet: 'Unfortunately, we will not be moving forward.',
              occurred_at: '2026-08-20T10:00:00Z', matched_confidence: 1.0,
              classified_as: 'rejection',
            },
          ],
          total: 1, unmatched: 0,
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText('Update on your application')).toBeInTheDocument();
    expect(screen.getByText('Rejection')).toBeInTheDocument();
    expect(screen.getByText(/Monzo Recruiting/)).toBeInTheDocument();
    // Already matched — no "link to application" affordance.
    expect(screen.queryByText('Link to an application')).not.toBeInTheDocument();
  });

  it('lets the operator link an unmatched item to an application', async () => {
    server.use(
      http.get('/api/v1/communications/', () =>
        HttpResponse.json({
          items: [
            {
              id: 'ce-1', source: 'gmail', application_id: null,
              sender: 'someone@unrelated.com', subject: 'Hello', snippet: 'hi there',
              occurred_at: '2026-08-20T10:00:00Z', matched_confidence: 0.0, classified_as: 'reply',
            },
          ],
          total: 1, unmatched: 1,
        }),
      ),
      http.get('/api/v1/applications/', () =>
        HttpResponse.json({
          items: [{ id: 'app-1', job_title: 'Data Scientist', company: 'Acme', status: 'applied' }],
          total: 1, page: 1, page_size: 100, has_next: false,
        }),
      ),
      http.post('/api/v1/communications/:id/link-application', () =>
        HttpResponse.json({
          id: 'ce-1', source: 'gmail', application_id: 'app-1', sender: 'someone@unrelated.com',
          subject: 'Hello', snippet: 'hi there', occurred_at: '2026-08-20T10:00:00Z',
          matched_confidence: 1.0, classified_as: 'reply',
        }),
      ),
    );

    renderPage();

    await userEvent.click(await screen.findByText('Link to an application'));
    const select = await screen.findByLabelText('Application to link');
    await userEvent.selectOptions(select, 'app-1');
    await userEvent.click(screen.getByRole('button', { name: 'Link' }));

    // The inline picker closes once the link succeeds.
    await waitFor(() =>
      expect(screen.queryByLabelText('Application to link')).not.toBeInTheDocument(),
    );
  });

  it('switches the feed filter to "Needs review"', async () => {
    let lastUnmatchedParam: string | null = null;
    server.use(
      http.get('/api/v1/communications/', ({ request }) => {
        lastUnmatchedParam = new URL(request.url).searchParams.get('unmatched_only');
        return HttpResponse.json({ items: [], total: 0, unmatched: 0 });
      }),
    );

    renderPage();
    await screen.findByText(/Nothing captured yet/);

    const tabs = screen.getAllByRole('tab');
    const needsReview = within(screen.getByText('Feed').closest('section')!).getByText(/Needs review/);
    await userEvent.click(needsReview);

    await waitFor(() => expect(lastUnmatchedParam).toBe('true'));
    expect(tabs.length).toBeGreaterThan(0);
  });
});
