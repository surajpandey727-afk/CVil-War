import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import JobSearchPage from '@/pages/JobSearchPage';

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: 'j1', platform: 'linkedin', platform_job_id: 'ln1', title: 'Senior Product Manager',
    company: 'Northwind Labs', location: 'San Francisco, CA', url: 'https://x', description: 'Own the roadmap.',
    salary_range: null, job_type: 'Full-time', remote: true, posted_date: '2026-07-08',
    experience_level: 'Senior', match_score: 0.9, skills_required: null, status: 'new',
    created_at: '2026-07-08T00:00:00Z', updated_at: '2026-07-08T00:00:00Z', ...overrides,
  };
}
const listOf = (...items: object[]) => ({ items, total: items.length, page: 1, page_size: 20, has_next: false });

function renderJobs() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <JobSearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('JobSearchPage', () => {
  it('renders job cards from the API', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
    renderJobs();
    expect(await screen.findByText('Senior Product Manager')).toBeInTheDocument();
    // Company is shown in the card subtitle (company · location), so match on substring.
    expect(screen.getByText(/Northwind Labs/)).toBeInTheDocument();
  });

  it('searches with the typed query', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
    let body: { query?: string } | null = null;
    server.use(http.post('/api/v1/jobs/search', async ({ request }) => {
      body = (await request.json()) as { query: string };
      return HttpResponse.json(listOf());
    }));
    renderJobs();
    await userEvent.type(screen.getByLabelText(/job title or keywords/i), 'product manager');
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body!.query).toBe('product manager');
  });

  it('analyzes an un-analyzed job via the endpoint', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job({ match_score: null })))));
    let analyzedId: string | null = null;
    server.use(http.post('/api/v1/jobs/:id/analyze', ({ params }) => {
      analyzedId = params.id as string;
      return HttpResponse.json({ job_id: 'j1', match_score: 0.88, skill_match: 0.9, keyword_match: 0.8, missing_skills: [], suggestions: [] });
    }));
    renderJobs();
    await screen.findByText('Senior Product Manager');
    await userEvent.click(screen.getByRole('button', { name: /analyze/i }));
    await waitFor(() => expect(analyzedId).toBe('j1'));
  });

  it('opens the job drawer with the analysis when a job title is clicked', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
    server.use(http.post('/api/v1/jobs/:id/analyze', () =>
      HttpResponse.json({ job_id: 'j1', match_score: 0.88, skill_match: 0.9, keyword_match: 0.8, missing_skills: ['GraphQL'], suggestions: ['Add GraphQL experience'] }),
    ));
    renderJobs();
    await userEvent.click(await screen.findByRole('button', { name: 'Senior Product Manager' }));
    expect(await screen.findByRole('dialog', { name: /job details/i })).toBeInTheDocument();
    expect(await screen.findByText('GraphQL')).toBeInTheDocument();
  });

  it('distinguishes "no results for this search" from "not searched yet" (BUG-008)', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf())));
    server.use(http.post('/api/v1/jobs/search', () => HttpResponse.json(listOf())));
    renderJobs();
    // Before any search: the pre-search empty state.
    expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument();
    // Run a search that returns nothing.
    await userEvent.type(screen.getByLabelText(/job title or keywords/i), 'unobtanium');
    await userEvent.click(screen.getByRole('button', { name: /^search$/i }));
    // Now the copy must reflect that a search ran and matched nothing.
    expect(await screen.findByText(/no matching roles/i)).toBeInTheDocument();
    expect(screen.queryByText(/no jobs yet/i)).not.toBeInTheDocument();
  });

  it('toggles a platform chip off', async () => {
    server.use(http.get('/api/v1/jobs/', () => HttpResponse.json(listOf(job()))));
    renderJobs();
    await screen.findByText('Senior Product Manager');
    const chip = screen.getByRole('button', { name: /linkedin/i });
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'false');
  });
});
