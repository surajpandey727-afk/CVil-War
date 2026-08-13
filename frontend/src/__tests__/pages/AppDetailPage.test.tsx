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
    expect(await screen.findByText('Senior Product Manager')).toBeInTheDocument();
    // Company is shown in the subtitle line (combined with mode + date), so match on substring.
    expect(screen.getByText(/Northwind Labs/)).toBeInTheDocument();
  });

  it('renders the run timeline for the application status + mode', async () => {
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp({ status: 'applied', apply_mode: 'review' }))));
    renderDetail();
    await screen.findByText('Senior Product Manager');
    // review-mode applied → the "Applied" step is the current one in the timeline.
    const applied = document.querySelector('[data-step="applied"]');
    expect(applied).not.toBeNull();
    expect(applied?.getAttribute('data-state')).toBe('current');
  });

  it('surfaces the failure diagnosis for a failed run', async () => {
    server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp({ status: 'failed', apply_mode: 'autonomous' }))));
    renderDetail();
    await screen.findByText('Senior Product Manager');
    expect(document.querySelector('[data-step="applying"]')?.getAttribute('data-state')).toBe('failed');
  });

  describe('documents sent', () => {
    it('names the CV that actually went to the employer', async () => {
      // The application already stored the résumé reference; before this panel existed the
      // one question a submitted application is for — "which CV did they get?" — had no
      // answer anywhere in the UI.
      server.use(http.get('/api/v1/applications/:appId', () => HttpResponse.json(fullApp())));
      renderDetail();

      expect(await screen.findByText('Suraj_Pandey_AIPM.pdf')).toBeInTheDocument();
      expect(screen.getByText(/tailored CV/)).toBeInTheDocument();
      expect(screen.getByText(/88% ATS/)).toBeInTheDocument();
    });

    it('still names an archived CV, and says that is why it is kept', async () => {
      // The payoff for archiving rather than deleting a used CV: the record survives.
      server.use(
        http.get('/api/v1/applications/:appId', () =>
          HttpResponse.json(fullApp({ resume_archived: true })),
        ),
      );
      renderDetail();

      expect(await screen.findByText('Suraj_Pandey_AIPM.pdf')).toBeInTheDocument();
      expect(screen.getByText(/archived, kept for this record/)).toBeInTheDocument();
    });

    it('says plainly when no CV was attached rather than showing an empty row', async () => {
      server.use(
        http.get('/api/v1/applications/:appId', () =>
          HttpResponse.json(fullApp({ resume_id: null, resume_name: null })),
        ),
      );
      renderDetail();

      expect(await screen.findByText(/no cv was attached/i)).toBeInTheDocument();
    });

    it('distinguishes a cover letter that was sent from one that was not', async () => {
      server.use(
        http.get('/api/v1/applications/:appId', () =>
          HttpResponse.json(fullApp({ has_cover_letter: true })),
        ),
      );
      renderDetail();

      expect(await screen.findByText(/tailored cover letter was generated/i)).toBeInTheDocument();
    });

    it('describes an unsent application in the future tense', async () => {
      // "What the employer received" is a lie for something still queued.
      server.use(
        http.get('/api/v1/applications/:appId', () =>
          HttpResponse.json(fullApp({ status: 'queued', applied_at: null })),
        ),
      );
      renderDetail();

      expect(await screen.findByText(/what will go out when this application is submitted/i))
        .toBeInTheDocument();
    });
  });
});
