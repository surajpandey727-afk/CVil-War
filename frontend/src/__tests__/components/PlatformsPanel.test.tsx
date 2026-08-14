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
});
