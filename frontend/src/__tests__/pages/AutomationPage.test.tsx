import { describe, it, expect } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import AutomationPage from '@/pages/AutomationPage';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AutomationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AutomationPage', () => {
  it('renders controls from the catalogue rather than a hard-coded list', async () => {
    // The default handler serves three rules across three groups. Nothing in the page names
    // any of them — that is the property under test, and it is what stops this screen from
    // drifting away from the rules the worker actually enforces.
    renderPage();

    expect(await screen.findByText('Applications per day')).toBeInTheDocument();
    expect(screen.getByText('Human oversight')).toBeInTheDocument();
    expect(screen.getByText('Volume & rate')).toBeInTheDocument();
    expect(screen.getByLabelText('Applications per day')).toHaveValue('20');
  });

  it('shows each rule with its clause reference and its reason for existing', async () => {
    renderPage();

    expect(await screen.findByText('§2.1')).toBeInTheDocument();
    expect(
      screen.getByText(/above a considered human pace/i),
    ).toBeInTheDocument();
  });

  it('presents a locked invariant as unchangeable and says where it is enforced', async () => {
    // The §1 clauses are shown so the operator can see what the system will not do.
    // Rendering one as an editable control would be a promise the UI cannot keep.
    renderPage();

    expect(await screen.findByText('Never invent experience')).toBeInTheDocument();
    expect(screen.getByText(/always on — not configurable/i)).toBeInTheDocument();
    expect(screen.getByText(/enforced by app.services.resume/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Never invent experience')).not.toBeInTheDocument();
  });

  it('renders a control kind it does not recognise as such instead of dropping it', async () => {
    // A rule the backend added and this build cannot draw must still be visible. Silently
    // omitting it would present an incomplete policy as a complete one.
    server.use(
      http.get('/api/v1/settings/automation-policy', () =>
        HttpResponse.json({
          policy_version: 2,
          document: 'docs/AUTOMATION_POLICY.md',
          groups: [
            {
              id: 'volume',
              title: 'Volume & rate',
              rules: [
                {
                  id: 'volume.new_shape',
                  clause: '§2.9',
                  title: 'Something newer than this build',
                  rationale: 'Added to the backend catalogue after this UI shipped.',
                  enforcement: 'gate',
                  verdict: 'hold',
                  locked: false,
                  control: { kind: 'colour_wheel', min: null, max: null, step: null, unit: '', options: [] },
                  field_name: 'max_per_day',
                  enforced_by: '',
                  value: 3,
                },
              ],
            },
          ],
          policy: { max_per_day: 3 },
        }),
      ),
    );
    renderPage();

    expect(await screen.findByText('Something newer than this build')).toBeInTheDocument();
    expect(screen.getByText(/not editable here/i)).toBeInTheDocument();
  });

  it('shows the kill switch as its own banner and states what pausing does', async () => {
    renderPage();

    expect(await screen.findByText('Automation is running')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('switch', { name: /automation running/i }));

    expect(screen.getByText('Automation is paused')).toBeInTheDocument();
    expect(screen.getByText(/everything queued stays queued/i)).toBeInTheDocument();
  });

  it('does not apply an edit until it is saved', async () => {
    // A policy screen that saves on change would rewrite the rules mid-drag, against a run
    // that may already be in flight.
    let put: Record<string, unknown> | null = null;
    server.use(
      http.put('/api/v1/settings/', async ({ request }) => {
        put = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({});
      }),
    );
    renderPage();

    await screen.findByLabelText('Applications per day');
    await userEvent.click(screen.getByRole('switch', { name: /automation running/i }));
    expect(put).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: /save policy/i }));
    await waitFor(() => expect(put).not.toBeNull());
    expect((put as unknown as { automation: { paused: boolean } }).automation.paused).toBe(true);
  });

  it('previews a candidate policy against the queue without saving it', async () => {
    let put = 0;
    server.use(http.put('/api/v1/settings/', () => { put += 1; return HttpResponse.json({}); }));
    renderPage();

    await userEvent.click(await screen.findByRole('button', { name: /test against my queue/i }));

    const panel = await screen.findByText(/what this policy would do right now/i);
    const section = panel.closest('section')!;
    expect(within(section).getByText(/would go out/)).toBeInTheDocument();
    // The backend's own reason, verbatim — re-wording it here is how a UI ends up explaining
    // a decision it did not make.
    expect(
      within(section).getByText('ATS match 61% is below your 75% threshold.'),
    ).toBeInTheDocument();
    expect(put).toBe(0);
  });

  it('clears a stale preview when the policy changes underneath it', async () => {
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: /test against my queue/i }));
    expect(await screen.findByText(/what this policy would do right now/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('switch', { name: /automation running/i }));

    // The numbers described the policy the preview ran against. Leaving them up would show
    // an answer to a question nobody is asking any more.
    expect(screen.queryByText(/what this policy would do right now/i)).not.toBeInTheDocument();
  });

  it('says the policy could not be loaded rather than showing an empty one', async () => {
    // "No rules loaded" and "no rules apply" look identical on screen and mean opposite
    // things. Only one of them is safe to leave running.
    server.use(
      http.get('/api/v1/settings/automation-policy', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    );
    renderPage();

    expect(await screen.findByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/the worker still enforces whatever is stored/i)).toBeInTheDocument();
  });
});
