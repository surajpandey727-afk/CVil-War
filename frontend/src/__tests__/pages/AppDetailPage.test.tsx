import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import AppDetailPage from '@/pages/AppDetailPage';

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
});
