import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import AppDetailPage from '@/pages/AppDetailPage';
import { useAppStore } from '@/store/useAppStore';

function fullApp(overrides: Record<string, unknown> = {}) {
  return {
    id: 'app-1', job_id: 'job-1', job_title: 'Senior Product Manager', company: 'Northwind Labs',
    resume_id: 'resume-1', resume_name: 'Suraj_Pandey_AIPM.pdf', resume_type: 'tailored',
    resume_ats_score: 0.88, resume_archived: false, has_cover_letter: false,
    status: 'applied', apply_mode: 'review', ats_score: 0.91,
    cover_letter_path: null, applied_at: '2026-07-08T10:00:00Z', response_date: null, notes: null,
    created_at: '2026-07-06T09:00:00Z', updated_at: '2026-07-08T10:00:00Z', ...overrides,
  };
}

function renderDetail(appId = 'app-1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/applications/${appId}`]}>
        <Routes>
          <Route path="/applications/:id" element={<AppDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AppDetailPage', () => {
  it('shows the application job title and company once loaded', async () => {
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp())));
    renderDetail();
    expect(
      await screen.findByRole('heading', { name: 'Senior Product Manager' }),
    ).toBeInTheDocument();
    // Company is shown in the subtitle line (combined with mode + date), so match on substring.
    expect(screen.getByText(/Northwind Labs · review mode/)).toBeInTheDocument();
  });

  it('renders the run timeline for the application status + mode', async () => {
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp({ status: 'applied', apply_mode: 'review' }))));
    renderDetail();
    await screen.findByRole('heading', { name: 'Senior Product Manager' });
    // review-mode applied → the "Applied" step is the current one in the timeline.
    const applied = document.querySelector('[data-step="applied"]');
    expect(applied).not.toBeNull();
    expect(applied?.getAttribute('data-state')).toBe('current');
  });

  it('surfaces the failure diagnosis for a failed run', async () => {
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp({ status: 'failed', apply_mode: 'autonomous' }))));
    renderDetail();
    await screen.findByRole('heading', { name: 'Senior Product Manager' });
    expect(document.querySelector('[data-step="applying"]')?.getAttribute('data-state')).toBe('failed');
  });

  it('renders the evidence panel alongside the timeline', async () => {
    // The right-hand column used to be empty. What lives there is tested in detail against
    // the panel itself; this only pins that the page actually mounts it with the id.
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp())));
    renderDetail();

    await screen.findByRole('heading', { name: 'Senior Product Manager' });
    expect(await screen.findByRole('link', { name: /open job/i })).toBeInTheDocument();
    expect(screen.getByText('AI Product Manager CV')).toBeInTheDocument();
  });

  it('no longer offers a "View job" button that only opened the jobs list', async () => {
    // It looked like it opened the job and did not. The panel's "Open job" uses the stored
    // URL, so the misleading duplicate is gone rather than sitting next to the real one.
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp())));
    renderDetail();

    await screen.findByRole('heading', { name: 'Senior Product Manager' });
    expect(screen.queryByRole('button', { name: /view job/i })).not.toBeInTheDocument();
  });

  it('shows live fill activity streamed in over the websocket while a run is in progress', async () => {
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp({ status: 'applying' }))));
    useAppStore.getState().appendFillStep('app-1', 'step 1: click_apply_button');
    useAppStore.getState().appendFillStep('app-1', 'step 2: fill_text_field(email)');
    renderDetail();

    await screen.findByRole('heading', { name: 'Senior Product Manager' });
    expect(await screen.findByText('Filling the form, live')).toBeInTheDocument();
    expect(screen.getByText('step 1: click_apply_button')).toBeInTheDocument();
    expect(screen.getByText('step 2: fill_text_field(email)')).toBeInTheDocument();
    useAppStore.getState().clearFillActivity('app-1'); // this store is a module-level singleton
  });

  it('does not show a fill activity panel for an application with no recorded steps', async () => {
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp({ id: 'app-no-steps' }))));
    renderDetail('app-no-steps');

    await screen.findByRole('heading', { name: 'Senior Product Manager' });
    expect(screen.queryByText(/fill activity/i)).not.toBeInTheDocument();
  });

  describe('résumé picker for an application missing one', () => {
    // Regression: the dashboard's "CV required" action used to route here to nothing —
    // AppDetailPage had no way to attach a résumé to an existing application at all, and
    // the backend had no endpoint for it either.

    it('shows a picker when no résumé is attached', async () => {
      server.use(
        http.get('/api/v1/applications/:appId', () =>
          HttpResponse.json(fullApp({ resume_id: null, resume_name: null }))),
      );
      server.use(
        http.get('/api/v1/resumes/', () => HttpResponse.json({
          items: [{ id: 'resume-9', name: 'Suraj_N_Pandey_MLOps.pdf' }],
          total: 1, page: 1, page_size: 20, has_next: false,
        })),
      );
      renderDetail();

      await screen.findByRole('heading', { name: 'Senior Product Manager' });
      expect(screen.getByText('No résumé selected')).toBeInTheDocument();
      expect(await screen.findByRole('option', { name: 'Suraj_N_Pandey_MLOps.pdf' })).toBeInTheDocument();
    });

    it('shows a picker when the attached résumé has been archived', async () => {
      server.use(
        http.get('/api/v1/applications/:appId', () =>
          HttpResponse.json(fullApp({ resume_archived: true }))),
      );
      renderDetail();

      await screen.findByRole('heading', { name: 'Senior Product Manager' });
      expect(screen.getByText('The résumé used here has since been archived')).toBeInTheDocument();
    });

    it('does not show a picker once a résumé is attached', async () => {
      server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp())));
      renderDetail();

      await screen.findByRole('heading', { name: 'Senior Product Manager' });
      expect(screen.queryByLabelText('Choose a résumé')).not.toBeInTheDocument();
    });

    it('attaches the picked résumé, sending the app id and resume id together', async () => {
      server.use(
        http.get('/api/v1/applications/:appId', () =>
          HttpResponse.json(fullApp({ resume_id: null, resume_name: null, status: 'queued' }))),
      );
      server.use(
        http.get('/api/v1/resumes/', () => HttpResponse.json({
          items: [{ id: 'resume-9', name: 'Suraj_N_Pandey_MLOps.pdf' }],
          total: 1, page: 1, page_size: 20, has_next: false,
        })),
      );
      let body: { status?: string; resume_id?: string } | null = null;
      server.use(
        http.put('/api/v1/applications/:appId/status', async ({ request }) => {
          body = (await request.json()) as { status: string; resume_id: string };
          return HttpResponse.json(fullApp({ resume_id: body.resume_id }));
        }),
      );
      renderDetail();

      await screen.findByRole('heading', { name: 'Senior Product Manager' });
      await userEvent.selectOptions(screen.getByLabelText('Choose a résumé'), 'resume-9');
      await userEvent.click(screen.getByRole('button', { name: /attach résumé/i }));

      await waitFor(() => expect(body).not.toBeNull());
      expect(body!.resume_id).toBe('resume-9');
      expect(body!.status).toBe('queued');
    });

    it('disables the attach button until a résumé is picked', async () => {
      server.use(
        http.get('/api/v1/applications/:appId', () =>
          HttpResponse.json(fullApp({ resume_id: null, resume_name: null }))),
      );
      renderDetail();

      await screen.findByRole('heading', { name: 'Senior Product Manager' });
      expect(screen.getByRole('button', { name: /attach résumé/i })).toBeDisabled();
    });
  });
});
