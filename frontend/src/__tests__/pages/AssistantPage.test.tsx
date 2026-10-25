import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import AssistantPage from '@/pages/AssistantPage';
import type { ChatMessage, ChatResponse } from '@/types/assistant';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/assistant']}><AssistantPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

const REPLY: ChatResponse = {
  reply: 'You have 3 strong UK matches.',
  tool_calls: [{ name: 'get_best_matches', input_summary: 'limit=5', ok: true, result_summary: '3 scored' }],
  pending: [],
  model: 'claude-sonnet-5-5',
};

/** Seed the chat endpoint; returns the captured request bodies. */
function seedChat(...responses: (ChatResponse | { status: number; detail: string })[]) {
  const bodies: { messages: ChatMessage[] }[] = [];
  const queue = [...responses];
  server.use(
    http.post('/api/v1/assistant/chat', async ({ request }) => {
      bodies.push((await request.json()) as { messages: ChatMessage[] });
      const next = queue.shift() ?? REPLY;
      if ('status' in next) return HttpResponse.json({ detail: next.detail }, { status: next.status });
      return HttpResponse.json(next);
    }),
  );
  return bodies;
}

describe('AssistantPage', () => {
  beforeEach(() => sessionStorage.clear());

  it('sends on Enter and shows the reply with tool chips', async () => {
    const bodies = seedChat(REPLY);
    renderPage();
    const input = screen.getByLabelText('Message the assistant');
    await userEvent.type(input, 'Best matches?{Enter}');

    expect(await screen.findByText('You have 3 strong UK matches.', { selector: '.as-bubble, .as-bubble *' })).toBeInTheDocument();
    const chips = screen.getByRole('list', { name: 'Tools used' });
    expect(within(chips).getByText('get_best_matches')).toBeInTheDocument();
    expect(within(chips).getByLabelText('succeeded')).toBeInTheDocument();
    expect(bodies[0]?.messages).toEqual([{ role: 'user', content: 'Best matches?' }]);
    expect(input).toHaveValue('');
  });

  it('Shift+Enter adds a new line instead of sending', async () => {
    const bodies = seedChat();
    renderPage();
    const input = screen.getByLabelText('Message the assistant');
    await userEvent.type(input, 'line one{Shift>}{Enter}{/Shift}line two');
    expect(input).toHaveValue('line one\nline two');
    expect(bodies).toHaveLength(0);
  });

  it('announces the reply in a polite live region', async () => {
    seedChat(REPLY);
    renderPage();
    await userEvent.click(screen.getByRole('button', { name: 'Show my best UK matches' }));
    await screen.findByText('You have 3 strong UK matches.', { selector: '.as-bubble, .as-bubble *' });
    const live = document.querySelector('[aria-live="polite"]');
    expect(live).toHaveTextContent('Assistant: You have 3 strong UK matches.');
  });

  it('shows a confirmation card and confirms through the token', async () => {
    seedChat({
      ...REPLY,
      reply: 'I can stage that for you.',
      pending: [{ token: 'tok-123', summary: 'Stage an application for “Data PM” at Acme.' }],
    });
    const confirmed: string[] = [];
    server.use(
      http.post('/api/v1/assistant/confirm', async ({ request }) => {
        confirmed.push(((await request.json()) as { token: string }).token);
        return HttpResponse.json({ ok: true, message: 'Staged: Data PM is waiting for your review.' });
      }),
    );
    renderPage();
    await userEvent.type(screen.getByLabelText('Message the assistant'), 'Apply to Data PM{Enter}');

    const card = await screen.findByRole('group', { name: 'Action awaiting confirmation' });
    expect(within(card).getByText(/Stage an application/)).toBeInTheDocument();
    expect(confirmed).toEqual([]);
    await userEvent.click(within(card).getByRole('button', { name: 'Confirm' }));
    expect(await within(card).findByText('Staged: Data PM is waiting for your review.')).toBeInTheDocument();
    expect(confirmed).toEqual(['tok-123']);
  });

  it('cancel changes nothing', async () => {
    seedChat({ ...REPLY, pending: [{ token: 'tok-9', summary: 'Approve 2 application(s).' }] });
    renderPage();
    await userEvent.type(screen.getByLabelText('Message the assistant'), 'approve them{Enter}');
    const card = await screen.findByRole('group', { name: 'Action awaiting confirmation' });
    await userEvent.click(within(card).getByRole('button', { name: 'Cancel' }));
    expect(within(card).getByText('Nothing was changed.')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument();
  });

  it('shows the server error and retries', async () => {
    const bodies = seedChat({ status: 503, detail: 'ANTHROPIC_API_KEY is not configured.' }, REPLY);
    renderPage();
    await userEvent.type(screen.getByLabelText('Message the assistant'), 'hello{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('ANTHROPIC_API_KEY is not configured.');
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByText('You have 3 strong UK matches.', { selector: '.as-bubble, .as-bubble *' });
    expect(bodies).toHaveLength(2);
    expect(bodies[1]?.messages).toEqual([{ role: 'user', content: 'hello' }]);
  });

  it('keeps history in session storage and sends it back', async () => {
    const bodies = seedChat(REPLY, { ...REPLY, reply: 'Second answer.' });
    const { unmount } = renderPage();
    await userEvent.type(screen.getByLabelText('Message the assistant'), 'first{Enter}');
    await screen.findByText('You have 3 strong UK matches.', { selector: '.as-bubble, .as-bubble *' });
    unmount();

    renderPage();
    expect(screen.getByText('first', { selector: '.as-bubble, .as-bubble *' })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Message the assistant'), 'second{Enter}');
    await screen.findByText('Second answer.', { selector: '.as-bubble, .as-bubble *' });
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]?.messages.map((m) => m.role)).toEqual(['user', 'assistant', 'user']);
  });
});
