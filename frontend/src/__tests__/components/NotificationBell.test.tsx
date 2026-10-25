import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import NotificationBell from '@/components/layout/NotificationBell';
import type { AppNotification } from '@/types/notifications';

function note(over: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 'n1', kind: 'best_match', severity: 'success',
    title: 'Strong match (82%): Senior PM at Monzo', body: 'Scores 82/100 against your latest résumé.',
    link: '/resume-checker?job=j1', created_at: new Date().toISOString(), read_at: null, emailed_at: null,
    ...over,
  };
}

function renderBell(items: AppNotification[], unread = items.filter((n) => !n.read_at).length) {
  const posts: string[] = [];
  server.use(
    http.get('/api/v1/notifications/', () => HttpResponse.json({ items, unread })),
    http.post('/api/v1/notifications/read-all', ({ request }) => { posts.push(new URL(request.url).pathname); return HttpResponse.json({ updated: unread }); }),
    http.post('/api/v1/notifications/:id/read', ({ request }) => { posts.push(new URL(request.url).pathname); return HttpResponse.json({ updated: 1 }); }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/dashboard" element={<NotificationBell />} />
          <Route path="/resume-checker" element={<p>checker page</p>} />
          <Route path="/applications/:id" element={<p>application page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return posts;
}

describe('NotificationBell', () => {
  it('shows the unread count in the badge and the accessible name', async () => {
    renderBell([note(), note({ id: 'n2', title: 'Applied: PM at Wise', kind: 'application_submitted' })]);
    expect(await screen.findByRole('button', { name: 'Notifications, 2 unread' })).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('lists notifications and opens the linked page, marking it read', async () => {
    const posts = renderBell([note()]);
    await userEvent.click(await screen.findByRole('button', { name: /Notifications, 1 unread/ }));
    const dialog = screen.getByRole('dialog', { name: 'Notifications' });
    expect(dialog).toHaveTextContent('Strong match (82%): Senior PM at Monzo');
    await userEvent.click(screen.getByText('Strong match (82%): Senior PM at Monzo'));
    expect(await screen.findByText('checker page')).toBeInTheDocument();
    await waitFor(() => expect(posts).toContain('/api/v1/notifications/n1/read'));
  });

  it('marks all read', async () => {
    const posts = renderBell([note(), note({ id: 'n2' })]);
    await userEvent.click(await screen.findByRole('button', { name: /2 unread/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    await waitFor(() => expect(posts).toContain('/api/v1/notifications/read-all'));
  });

  it('says plainly when there is nothing yet, and offers no badge', async () => {
    renderBell([]);
    await userEvent.click(await screen.findByRole('button', { name: 'Notifications' }));
    expect(screen.getByText(/Nothing yet/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mark all read' })).not.toBeInTheDocument();
  });

  it('marks an emailed notification as such', async () => {
    renderBell([note({ emailed_at: new Date().toISOString() })]);
    await userEvent.click(await screen.findByRole('button', { name: /1 unread/ }));
    expect(screen.getByText('Also emailed')).toBeInTheDocument();
  });

  it('closes on Escape', async () => {
    renderBell([note()]);
    await userEvent.click(await screen.findByRole('button', { name: /1 unread/ }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
