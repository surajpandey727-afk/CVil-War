import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { server } from '@/__tests__/mocks/server';
import JobDrawer from '@/components/jobs/JobDrawer';
import type { Job } from '@/types/job';
import type { Resume } from '@/types/resume';

const job = (o: Partial<Job> = {}): Job => ({
  id: 'job-1', platform: 'reed', platform_job_id: 'r1',
  title: 'Senior Product Manager', company: 'Zartis', location: 'London, UK',
  url: 'https://www.reed.co.uk/jobs/senior-product-manager/56654149',
  description: 'We need a PM.\n\nYou will own the roadmap.',
  salary_range: '£75,000 - £95,000', job_type: 'full-time', remote: false,
  posted_date: null, experience_level: 'Senior', match_score: 0.72,
  skills_required: null, status: 'new',
  created_at: '2026-08-13T00:00:00Z', updated_at: '2026-08-13T00:00:00Z',
  ...o,
} as Job);

const resumes: Resume[] = [
  {
    id: 'resume-1', name: 'AI Product Manager CV', type: 'base', template_id: 'modern',
    base_resume_id: null, job_id: null, has_pdf: true, has_docx: false, ats_score: 0.88,
    used_in_applications: 0, submitted_applications: 0, archived: false,
    created_at: '2026-08-12T00:00:00Z', updated_at: '2026-08-12T00:00:00Z',
  },
];

function renderDrawer(props: Partial<Parameters<typeof JobDrawer>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const handlers = {
    onClose: vi.fn(), onApplyWithAgent: vi.fn(), onApplyManually: vi.fn(),
    onOpenJobId: vi.fn(),
  };
  render(
    <QueryClientProvider client={qc}>
      <JobDrawer
        job={job()}
        resumes={resumes}
        applying={false}
        {...handlers}
        {...props}
      />
    </QueryClientProvider>,
  );
  return handlers;
}

describe('JobDrawer as the decision centre', () => {
  it('shows the posting facts needed to judge it', async () => {
    renderDrawer();

    expect(screen.getByText('Senior Product Manager')).toBeInTheDocument();
    expect(screen.getByText(/Zartis/)).toBeInTheDocument();
    expect(screen.getByText(/London, UK/)).toBeInTheDocument();
    expect(screen.getByText(/£75,000 - £95,000/)).toBeInTheDocument();
  });

  it('selects the CV here, against this job, rather than on another screen', () => {
    // The whole point of the job-first flow: opening a job establishes the context and the
    // CV is the variable. The opposite order is what this replaces.
    renderDrawer();

    const select = screen.getByLabelText('CV') as HTMLSelectElement;
    expect(select.value).toBe('resume-1');
    expect(screen.getByRole('button', { name: /analyse my fit/i })).toBeInTheDocument();
  });

  it('runs the analysis against the selected CV and shows the breakdown', async () => {
    let posted: { resume_id?: string } | null = null;
    server.use(
      http.post('/api/v1/jobs/:jobId/fit', async ({ request }) => {
        posted = (await request.json()) as { resume_id?: string };
        return HttpResponse.json({
          job_id: 'job-1', resume_id: 'resume-1', resume_name: 'AI Product Manager CV',
          overall: 0.78,
          categories: [
            { key: 'required_skills', label: 'Required skills', score: 0.84, rationale: '5 of 6 evidenced.', method: 'Average of match levels.' },
          ],
          not_assessed: ['Salary — the posting publishes no band.'],
          matches: [], recommendations: [], method: 'llm', model: 'Full-Send',
          analysed_at: '2026-08-14T08:00:00Z', cached: false, stale_reason: '',
        });
      }),
    );
    renderDrawer();

    await userEvent.click(screen.getByRole('button', { name: /analyse my fit/i }));

    expect(await screen.findByText('78%')).toBeInTheDocument();
    expect(screen.getByText('Required skills')).toBeInTheDocument();
    expect(posted!.resume_id).toBe('resume-1');
  });

  it('opens the real stored URL when applying manually, and claims nothing', async () => {
    // Opening a tab is not evidence that anybody submitted anything.
    const handlers = renderDrawer();

    const link = screen.getByRole('link', { name: /apply manually/i });
    expect(link).toHaveAttribute(
      'href', 'https://www.reed.co.uk/jobs/senior-product-manager/56654149',
    );
    expect(link).toHaveAttribute('target', '_blank');

    await userEvent.click(link);
    expect(handlers.onApplyManually).toHaveBeenCalledWith(
      'https://www.reed.co.uk/jobs/senior-product-manager/56654149',
    );
  });

  it('prefers the application URL over the advert when the source distinguishes them', () => {
    renderDrawer({ job: job({ application_url: 'https://apply.zartis.com/9910' }) });

    expect(screen.getByRole('link', { name: /apply manually/i })).toHaveAttribute(
      'href', 'https://apply.zartis.com/9910',
    );
  });

  it('says so rather than rendering a dead manual-apply button', () => {
    renderDrawer({ job: job({ url: '', application_url: null }) });

    expect(screen.queryByRole('link', { name: /apply manually/i })).not.toBeInTheDocument();
    expect(screen.getByText(/no application URL was stored/i)).toBeInTheDocument();
  });

  it('hands the chosen CV to the agent route', async () => {
    const handlers = renderDrawer();

    await userEvent.click(screen.getByRole('button', { name: /apply with agent/i }));
    expect(handlers.onApplyWithAgent).toHaveBeenCalledWith('resume-1');
  });

  it('shows what is known about the employer and states what is not', async () => {
    server.use(
      http.get('/api/v1/jobs/:jobId/company', () =>
        HttpResponse.json({
          name: 'Zartis', available: true, website: 'https://zartis.com',
          website_source: 'career-page registry', industry: null, description: null,
          source: 'careers:zartis', other_jobs: [], other_jobs_count: 0,
          unavailable_fields: ['Industry', 'Company size', 'Headquarters'],
          unavailable_reason: 'Company details would need a paid enrichment service.',
        }),
      ),
    );
    renderDrawer();

    await userEvent.click(screen.getByRole('button', { name: 'Company' }));

    expect(await screen.findByRole('link', { name: /visit company website/i }))
      .toHaveAttribute('href', 'https://zartis.com');
    expect(screen.getByText(/no other roles from Zartis/i)).toBeInTheDocument();
    expect(screen.getByText(/Company size/)).toBeInTheDocument();
  });

  it('says the website is unavailable rather than guessing a domain', async () => {
    // A confident dead link on a decision page is worse than an honest blank.
    server.use(
      http.get('/api/v1/jobs/:jobId/company', () =>
        HttpResponse.json({
          name: 'Acme', available: false, website: null, website_source: '',
          industry: null, description: null, source: 'arbeitnow',
          other_jobs: [], other_jobs_count: 0,
          unavailable_fields: ['Website', 'Industry'],
          unavailable_reason: 'This job came from an aggregator.',
        }),
      ),
    );
    renderDrawer();

    await userEvent.click(screen.getByRole('button', { name: 'Company' }));

    expect(await screen.findByText(/company website unavailable/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /visit company website/i })).not.toBeInTheDocument();
  });

  it('states plainly when the source published no description', async () => {
    renderDrawer({ job: job({ description: '' }) });

    await userEvent.click(screen.getByRole('button', { name: 'Description' }));
    expect(screen.getByText(/published no description/i)).toBeInTheDocument();
  });

  it('closes', async () => {
    const handlers = renderDrawer();
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => expect(handlers.onClose).toHaveBeenCalled());
  });
});
