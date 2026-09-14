import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

import { server } from '@/__tests__/mocks/server';
import { useFocusStore } from '@/store/useFocusStore';
import FloatingAtsWidget from '@/components/ats/FloatingAtsWidget';

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('FloatingAtsWidget', () => {
  beforeEach(() => {
    useFocusStore.setState({ focusedJobId: null, focusedJobTitle: '' });
    localStorage.clear();
  });

  it('renders nothing when no job is in focus', () => {
    render(<FloatingAtsWidget />, { wrapper: wrapper() });
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  });

  it('shows the recommended résumé, score, and synopsis for the focused job', async () => {
    useFocusStore.setState({ focusedJobId: 'job-1', focusedJobTitle: 'Senior Data Scientist' });
    server.use(
      http.get('/api/v1/jobs/:jobId/resume-recommendation', () =>
        HttpResponse.json({
          job_id: 'job-1',
          recommended_resume_id: 'resume-1',
          rankings: [
            {
              resume_id: 'resume-1', resume_name: 'Tailored CV',
              score: {
                resume_id: 'resume-1', job_id: 'job-1', overall_score: 0.84,
                skill_score: 0.8, experience_score: 0.8, education_score: 0.8,
                keyword_score: 0.8, missing_skills: [], suggestions: [],
              },
            },
          ],
          synopsis: '"Tailored CV" scores highest at 84% match.',
        }),
      ),
    );

    render(<FloatingAtsWidget />, { wrapper: wrapper() });

    expect(await screen.findByText('Senior Data Scientist')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('84%')).toBeInTheDocument());
    expect(screen.getByText('Tailored CV')).toBeInTheDocument();
    expect(screen.getByText(/scores highest at 84% match/)).toBeInTheDocument();
  });

  it('collapses and expands on toggle, persisting the score in the collapsed header', async () => {
    useFocusStore.setState({ focusedJobId: 'job-1', focusedJobTitle: 'Senior Data Scientist' });
    server.use(
      http.get('/api/v1/jobs/:jobId/resume-recommendation', () =>
        HttpResponse.json({
          job_id: 'job-1',
          recommended_resume_id: 'resume-1',
          rankings: [
            {
              resume_id: 'resume-1', resume_name: 'Tailored CV',
              score: {
                resume_id: 'resume-1', job_id: 'job-1', overall_score: 0.5,
                skill_score: 0.5, experience_score: 0.5, education_score: 0.5,
                keyword_score: 0.5, missing_skills: [], suggestions: [],
              },
            },
          ],
          synopsis: 'x',
        }),
      ),
    );

    render(<FloatingAtsWidget />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText('Tailored CV')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /collapse/i }));
    expect(screen.queryByText('Tailored CV')).not.toBeInTheDocument();
    expect(screen.getByText('50% match')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /expand/i }));
    expect(await screen.findByText('Tailored CV')).toBeInTheDocument();
  });

  it('shows an honest empty state when the user has no résumés', async () => {
    useFocusStore.setState({ focusedJobId: 'job-1', focusedJobTitle: 'Senior Data Scientist' });
    server.use(
      http.get('/api/v1/jobs/:jobId/resume-recommendation', () =>
        HttpResponse.json({
          job_id: 'job-1', recommended_resume_id: null, rankings: [],
          synopsis: 'No résumés uploaded yet — add one to see a match score for this job.',
        }),
      ),
    );

    render(<FloatingAtsWidget />, { wrapper: wrapper() });
    expect(await screen.findByText(/No résumés uploaded yet/)).toBeInTheDocument();
  });
});
