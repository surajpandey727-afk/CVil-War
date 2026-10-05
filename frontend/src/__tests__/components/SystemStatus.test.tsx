import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';

import SystemStatus from '@/components/ui/SystemStatus';
import { server } from '@/__tests__/mocks/server';

function renderWidget(wsConnected = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SystemStatus wsConnected={wsConnected} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const status = (over: Partial<Record<string, unknown>> = {}) => ({
  services: [
    { key: 'ai_agent', label: 'AI apply agent', status: 'pending', detail: 'Review mode.', action_path: '/settings', action_label: 'Change' },
    { key: 'llm', label: 'AI model gateway', status: 'connected', detail: 'Reachable.', action_path: '', action_label: '' },
    { key: 'gmail', label: 'Gmail notifications', status: 'pending', detail: 'Not connected.', action_path: '/communications', action_label: 'Connect' },
    { key: 'job_boards', label: 'Job boards (apply)', status: 'pending', detail: 'None connected.', action_path: '/settings', action_label: 'Connect' },
    { key: 'database', label: 'Database', status: 'connected', detail: 'Connected.', action_path: '', action_label: '' },
  ],
  all_ok: false,
  attention: 3,
  ...over,
});

describe('SystemStatus — the one honest connection surface', () => {
  it('summarises how many dependencies need connecting, then lists them with actions on open', async () => {
    server.use(http.get('/api/v1/system/status', () => HttpResponse.json(status())));
    renderWidget(false);

    expect(await screen.findByText('3 to connect')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /system status/i }));

    expect(screen.getByText('Gmail notifications')).toBeInTheDocument();
    expect(screen.getByText('AI model gateway')).toBeInTheDocument();
    // Live updates row reflects the websocket, and "pending" there is not an error.
    expect(screen.getByText('Live updates')).toBeInTheDocument();
    // Pending dependencies carry a one-click action.
    expect(screen.getAllByRole('button', { name: 'Connect' }).length).toBeGreaterThanOrEqual(2);
  });

  it('says all connected when nothing needs attention', async () => {
    server.use(http.get('/api/v1/system/status', () =>
      HttpResponse.json(status({ attention: 0, all_ok: true,
        services: [{ key: 'llm', label: 'AI model gateway', status: 'connected', detail: 'ok', action_path: '', action_label: '' }] }))));
    renderWidget(true);
    await waitFor(() => expect(screen.getByText('All connected')).toBeInTheDocument());
  });
});
