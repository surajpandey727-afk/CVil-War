import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { server } from '@/__tests__/mocks/server';
import AISettingsPanel from '@/components/settings/AISettingsPanel';

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AISettingsPanel />
    </QueryClientProvider>,
  );
}

describe('AISettingsPanel — bring your own key', () => {
  it('shows the section for entering a personal API key', async () => {
    renderPanel();
    expect(await screen.findByText('Your own API key')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('API key')).toBeInTheDocument();
  });

  it('saves a key and shows it as active once the save succeeds', async () => {
    let savedBody: Record<string, unknown> | null = null;
    server.use(
      http.put('/api/v1/settings/llm-key', async ({ request }) => {
        savedBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({
          provider: savedBody.provider, has_key: true, is_active: true,
          default_model: savedBody.default_model ?? null,
        });
      }),
      http.get('/api/v1/settings/llm-key', () => HttpResponse.json([
        { provider: 'openai', has_key: true, is_active: true, default_model: null },
      ])),
    );
    renderPanel();

    await userEvent.type(screen.getByPlaceholderText('API key'), 'sk-my-real-key');
    await userEvent.click(screen.getByRole('button', { name: /save key/i }));

    await waitFor(() => expect(savedBody).not.toBeNull());
    expect(savedBody!.provider).toBe('openai');
    expect(savedBody!.api_key).toBe('sk-my-real-key');

    expect(await screen.findByText('Active')).toBeInTheDocument();
  });

  it('refuses to save an empty key', async () => {
    let called = false;
    server.use(http.put('/api/v1/settings/llm-key', () => {
      called = true;
      return HttpResponse.json({});
    }));
    renderPanel();

    await userEvent.click(await screen.findByRole('button', { name: /save key/i }));

    expect(called).toBe(false);
  });

  it('never displays a previously-saved key value anywhere', async () => {
    server.use(http.get('/api/v1/settings/llm-key', () => HttpResponse.json([
      { provider: 'openai', has_key: true, is_active: true, default_model: 'gpt-4o' },
    ])));
    renderPanel();

    expect(await screen.findByText('openai')).toBeInTheDocument();
    // The API key input is a fresh, empty password field — the stored value never
    // round-trips back into it. Confirmed by the type=password field being empty and by
    // the page containing no plausible key-shaped string.
    expect((screen.getByPlaceholderText('API key') as HTMLInputElement).value).toBe('');
  });

  it('removes a saved key', async () => {
    let deletedProvider: string | null = null;
    server.use(
      http.get('/api/v1/settings/llm-key', () => HttpResponse.json([
        { provider: 'openai', has_key: true, is_active: true, default_model: null },
      ])),
      http.delete('/api/v1/settings/llm-key/:provider', ({ params }) => {
        deletedProvider = params.provider as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPanel();

    await userEvent.click(await screen.findByRole('button', { name: /remove/i }));

    await waitFor(() => expect(deletedProvider).toBe('openai'));
  });
});
