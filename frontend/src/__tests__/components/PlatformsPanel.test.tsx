import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { server } from '@/__tests__/mocks/server';
import PlatformsPanel from '@/components/settings/PlatformsPanel';

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PlatformsPanel />
    </QueryClientProvider>,
  );
}

describe('PlatformsPanel', () => {
  it('renders the registry rather than a list kept on this page', async () => {
    // Settings used to hard-code four platforms while the registry served fifty-five, so the
    // two screens disagreed about what the product supports.
    renderPanel();

    expect(await screen.findByText('Remotive')).toBeInTheDocument();
    expect(screen.getByText('LinkedIn')).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 sources have a working adapter/)).toBeInTheDocument();
  });

  it('shows a connected account masked, never in full', async () => {
    renderPanel();

    expect(await screen.findByText('sur***@example.com')).toBeInTheDocument();
    expect(screen.getByText('CONNECTED')).toBeInTheDocument();
  });

  it('disables an action and says why rather than failing on click', async () => {
    // A control that cannot do anything must explain itself; a button that silently does
    // nothing is the defect this replaced.
    renderPanel();

    await screen.findByText('Remotive');
    await userEvent.click(screen.getByRole('button', { name: /^All 3$/ }));

    const enable = await screen.findByTitle(/no adapter can serve this source yet/i);
    expect(enable).toBeDisabled();
  });

  it('reports why a catalogued source is unavailable', async () => {
    renderPanel();
    await screen.findByText('Remotive');
    await userEvent.click(screen.getByRole('button', { name: /^All 3$/ }));

    expect(await screen.findByText('No public ATS board found.')).toBeInTheDocument();
  });

  it('filters to the sources that can actually return results by default', async () => {
    renderPanel();

    await screen.findByText('Remotive');
    // careers:starling has no adapter, so it is not in the default "usable" view.
    expect(screen.queryByText('Starling Bank')).not.toBeInTheDocument();
  });

  it('disconnects a platform through the real endpoint', async () => {
    let deleted: string | null = null;
    server.use(
      http.delete('/api/v1/platform-sessions/:platform', ({ params }) => {
        deleted = params['platform'] as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPanel();

    await screen.findByText('LinkedIn');
    await userEvent.click(screen.getByRole('button', { name: /disconnect/i }));

    await waitFor(() => expect(deleted).toBe('linkedin'));
  });

  it('says the registry could not be loaded rather than showing an empty list', async () => {
    server.use(
      http.get('/api/v1/settings/platforms', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderPanel();

    expect(await screen.findByText(/could not load platforms/i)).toBeInTheDocument();
    expect(screen.getByText(/your connections are unaffected/i)).toBeInTheDocument();
  });

  describe('connecting a platform the operator must sign in to', () => {
    // The dead end this closes: the server has always offered a `connect` action and the API
    // could store a session, but nothing in the UI rendered the control — so a platform that
    // needed a login had no route to one. "How can you apply if you don't have creds?" was a
    // fair question with no answer on screen.

    it('offers Reconnect for a platform behind a login', async () => {
      renderPanel();
      expect(await screen.findByRole('button', { name: 'Reconnect' })).toBeEnabled();
    });

    it('explains why a keyless source cannot be connected instead of hiding the control', async () => {
      renderPanel();
      await screen.findByText('Remotive');

      const connect = await screen.findByTitle(/public API and needs no login/i);
      expect(connect).toBeDisabled();
    });

    it('opens the guided sign-in and states that no password is kept', async () => {
      renderPanel();
      await userEvent.click(await screen.findByRole('button', { name: 'Reconnect' }));

      const dialog = await screen.findByRole('dialog', { name: /connect linkedin/i });
      // The promise belongs on the screen that asks for the sign-in, not only in the docs.
      expect(dialog).toHaveTextContent(/never sees it, never\s+stores it/i);
      expect(dialog).toHaveTextContent(/own page/i);
    });

    it('closes itself once the session has been captured', async () => {
      renderPanel();
      await userEvent.click(await screen.findByRole('button', { name: 'Reconnect' }));
      await screen.findByRole('dialog', { name: /connect linkedin/i });

      // Success needs no dismissal: the dialog stands down and the row refetches.
      await waitFor(
        () => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
        { timeout: 4000 },
      );
    });

    it('keeps waiting while the operator is still signing in', async () => {
      server.use(
        http.get('/api/v1/platform-sessions/connect/:id', ({ params }) =>
          HttpResponse.json({
            id: params['id'], platform: 'linkedin', state: 'awaiting_login', done: false,
            instructions: 'Sign in to LinkedIn as you normally would.',
            detail: '', seconds_remaining: 540,
          }),
        ),
      );
      renderPanel();
      await userEvent.click(await screen.findByRole('button', { name: 'Reconnect' }));

      expect(await screen.findByText(/waiting for you to sign in/i)).toBeInTheDocument();
      // Still in progress, so the escape hatch must be Cancel rather than Close.
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    });

    it('surfaces a failed sign-in verbatim rather than a generic error', async () => {
      server.use(
        http.get('/api/v1/platform-sessions/connect/:id', ({ params }) =>
          HttpResponse.json({
            id: params['id'], platform: 'linkedin', state: 'timed_out', done: true,
            instructions: '',
            detail: 'No completed sign-in was detected within 10 minutes.',
            seconds_remaining: 0,
          }),
        ),
      );
      renderPanel();
      await userEvent.click(await screen.findByRole('button', { name: 'Reconnect' }));

      expect(
        await screen.findByText(
          /no completed sign-in was detected within 10 minutes/i, {}, { timeout: 4000 },
        ),
      ).toBeInTheDocument();
      // Settled, so the operator gets a Close rather than a Cancel.
      expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    });
  });

  describe('verifying sources and acting on many at once', () => {
    // "Settings shows them but nothing works — how can I verify?" was fair: the Test control
    // was rendered against an endpoint that did not exist.

    it('probes every source and reports what actually answered', async () => {
      server.use(
        http.post('/api/v1/settings/platforms/test', () =>
          HttpResponse.json({
            tested: 2, passed: 1, failed: 1, elapsed_ms: 1400,
            results: [
              { key: 'remotive', label: 'Remotive', state: 'live', detail: '10 returned', results: 10, elapsed_ms: 550, ok: true },
              { key: 'linkedin', label: 'LinkedIn', state: 'unavailable', detail: 'LinkedIn rate-limited this search.', results: 0, elapsed_ms: 830, ok: false },
            ],
          }),
        ),
      );
      renderPanel();
      await userEvent.click(await screen.findByRole('button', { name: 'Test all' }));

      expect(await screen.findByText('Verified')).toBeInTheDocument();
      expect(screen.getByText('10 returned')).toBeInTheDocument();
      // A failure shows the upstream's own words, not a generic message.
      expect(screen.getByText('LinkedIn rate-limited this search.')).toBeInTheDocument();
      expect(screen.getByText('Failed')).toBeInTheDocument();
    });

    it('bulk actions stay disabled until something is selected', async () => {
      renderPanel();
      await screen.findByText('Remotive');

      expect(screen.getByRole('button', { name: 'Enable selected' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Disable selected' })).toBeDisabled();
    });

    it('selecting sources arms the bulk actions and reports the count', async () => {
      renderPanel();
      await userEvent.click(await screen.findByLabelText('Select Remotive'));

      expect(screen.getByText('1 selected')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Enable selected' })).toBeEnabled();
    });

    it('select-all ticks every listed source', async () => {
      renderPanel();
      await userEvent.click(await screen.findByLabelText('Select every listed source'));

      expect(await screen.findByText(/\d+ selected/)).toBeInTheDocument();
      expect(screen.getByLabelText('Select Remotive')).toBeChecked();
    });

    it('applies a bulk enable in one request', async () => {
      let sent: unknown = null;
      server.use(
        http.put('/api/v1/settings/platforms/bulk', async ({ request }) => {
          sent = await request.json();
          return HttpResponse.json({ platforms: [], total: 0, usable: 0, connected: 0 });
        }),
      );
      renderPanel();
      await userEvent.click(await screen.findByLabelText('Select Remotive'));
      await userEvent.click(screen.getByRole('button', { name: 'Enable selected' }));

      await waitFor(() => expect(sent).toEqual({ keys: ['remotive'], enabled: true }));
    });
  });
});
