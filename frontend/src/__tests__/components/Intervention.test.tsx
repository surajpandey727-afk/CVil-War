import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { server } from '@/__tests__/mocks/server';
import { useAppStore } from '@/store/useAppStore';
import { useApplicationEvents } from '@/hooks/useApplicationEvents';
import InterventionModal from '@/components/applications/InterventionModal';

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('intervention flow', () => {
  beforeEach(() => useAppStore.setState({ pendingIntervention: null }));

  it('surfaces a pending intervention from the WS event', () => {
    renderHook(
      () => useApplicationEvents({ type: 'intervention_required', payload: { application_id: 'app-1', kind: 'captcha', prompt: 'Solve the challenge' } }),
      { wrapper: wrapper() },
    );
    expect(useAppStore.getState().pendingIntervention?.application_id).toBe('app-1');
    expect(useAppStore.getState().pendingIntervention?.prompt).toMatch(/solve the challenge/i);
  });

  it('renders nothing when there is no pending intervention', () => {
    render(<InterventionModal />, { wrapper: wrapper() });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows the prompt and resolves a 2FA code via the endpoint, then clears', async () => {
    useAppStore.setState({ pendingIntervention: { application_id: 'app-1', kind: '2fa', prompt: 'Enter the 6-char code' } });
    let body: { id?: string; response?: string } | null = null;
    server.use(http.post('/api/v1/applications/:id/intervention', async ({ request, params }) => {
      body = { id: params.id as string, ...(await request.json() as { response: string }) };
      return HttpResponse.json({ resolved: true });
    }));

    render(<InterventionModal />, { wrapper: wrapper() });
    expect(screen.getByText(/enter the 6-char code/i)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/your response/i), 'ABC123');
    await userEvent.click(screen.getByRole('button', { name: /submit|resolve|verify/i }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.id).toBe('app-1');
    expect(body!.response).toBe('ABC123');
    await waitFor(() => expect(useAppStore.getState().pendingIntervention).toBeNull());
  });

  it('shows the URL and resumes a CAPTCHA blocker via resolve-blocker, then clears', async () => {
    useAppStore.setState({
      pendingIntervention: {
        application_id: 'app-1',
        kind: 'captcha',
        prompt: 'Solve the challenge',
        url: 'https://example.com/jobs/apply/123',
      },
    });
    let resolvedId: string | null = null;
    server.use(http.post('/api/v1/applications/:id/resolve-blocker', ({ params }) => {
      resolvedId = params.id as string;
      return HttpResponse.json({ queued: true });
    }));

    render(<InterventionModal />, { wrapper: wrapper() });
    expect(screen.getByText(/solve the challenge/i)).toBeInTheDocument();
    expect(screen.getByText('https://example.com/jobs/apply/123')).toBeInTheDocument();
    expect(screen.queryByLabelText(/your response/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /resume/i }));

    await waitFor(() => expect(resolvedId).toBe('app-1'));
    await waitFor(() => expect(useAppStore.getState().pendingIntervention).toBeNull());
  });

  it('shows the screenshot and approves a submission via the intervention endpoint, then clears', async () => {
    useAppStore.setState({
      pendingIntervention: {
        application_id: 'app-1',
        kind: 'submit_confirmation',
        prompt: 'Ready to submit to Acme: Data Analyst application',
        url: 'https://example.com/jobs/apply/123',
        screenshot_b64: 'ZmFrZS1wbmc=',
      },
    });
    let body: { id?: string; response?: string } | null = null;
    server.use(http.post('/api/v1/applications/:id/intervention', async ({ request, params }) => {
      body = { id: params.id as string, ...(await request.json() as { response: string }) };
      return HttpResponse.json({ resolved: true });
    }));

    render(<InterventionModal />, { wrapper: wrapper() });
    expect(screen.getByText(/ready to submit to acme/i)).toBeInTheDocument();
    expect(screen.getByAltText(/form the agent is about to submit/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/your response/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /approve & submit/i }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.id).toBe('app-1');
    expect(body!.response).toBe('approved');
    await waitFor(() => expect(useAppStore.getState().pendingIntervention).toBeNull());
  });

  it('rejects a submission via the intervention endpoint, then clears', async () => {
    useAppStore.setState({
      pendingIntervention: {
        application_id: 'app-1',
        kind: 'submit_confirmation',
        prompt: 'Ready to submit to Acme: Data Analyst application',
      },
    });
    let body: { id?: string; response?: string } | null = null;
    server.use(http.post('/api/v1/applications/:id/intervention', async ({ request, params }) => {
      body = { id: params.id as string, ...(await request.json() as { response: string }) };
      return HttpResponse.json({ resolved: true });
    }));

    render(<InterventionModal />, { wrapper: wrapper() });
    await userEvent.click(screen.getByRole('button', { name: /reject/i }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.response).toBe('rejected');
    await waitFor(() => expect(useAppStore.getState().pendingIntervention).toBeNull());
  });
});
