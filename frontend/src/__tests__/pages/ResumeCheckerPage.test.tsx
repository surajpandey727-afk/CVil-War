import { describe, it, expect } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import ResumeCheckerPage from '@/pages/ResumeCheckerPage';
import type { ResumeCheckResponse, ResumeReviewResponse } from '@/types/resumeCheck';

const ROLES = ['AI Product Manager', 'Product Manager', 'Product Analyst', 'Technical Product Manager', 'ML Engineer'];

function checkBody(over: Partial<ResumeCheckResponse> = {}): ResumeCheckResponse {
  return {
    resume_id: 'r1',
    resume_name: 'Suraj_AIPM.pdf',
    target: { kind: 'job', job_id: 'job-1', title: 'Senior Frontend Engineer', company: 'Acme Corp', role_titles: [] },
    score: {
      overall: 0.64,
      band: 'decent',
      components: [
        { key: 'must', label: 'Must-have skills', weight: 0.5, score: 0.8, detail: '4 of 5 must-haves evidenced' },
        { key: 'nice', label: 'Nice-to-have skills', weight: 0.2, score: 0.5, detail: '2 of 4 nice-to-haves' },
        { key: 'ats', label: 'ATS keywords', weight: 0.3, score: 0.4, detail: '4 of 10 keywords' },
      ],
      formula: '0.50 × must-have + 0.20 × nice-to-have + 0.30 × ATS keywords',
    },
    matched_skills: [
      { key: 'roadmap', label: 'Product roadmapping', category: 'Product craft', must_have: true,
        evidence: [{ quote: 'Owned the 12-month roadmap for the payments platform', section: 'experience' }] },
    ],
    missing_skills: [
      { key: 'genai', label: 'Generative AI / LLMs', category: 'AI / ML', must_have: true, uk_demand: 42, uk_demand_share: 0.42 },
      { key: 'sql', label: 'SQL', category: 'Data', must_have: true, uk_demand: 30, uk_demand_share: 0.3 },
      { key: 'figma', label: 'Figma', category: 'Design', must_have: false, uk_demand: 12, uk_demand_share: 0.12 },
    ],
    ats_keywords: { coverage: 0.4, total: 10, found: ['roadmap', 'stakeholders'], missing: ['LLM', 'A/B testing'] },
    sections: [
      { key: 'summary', label: 'Summary', status: 'needs_work', score: 0.5, findings: ['Summary does not name the target role.'] },
      { key: 'experience', label: 'Experience bullets', status: 'good', score: 0.8, findings: [] },
    ],
    suggestions: [
      { section: 'summary', kind: 'rewrite', original: 'Product person.', suggested: 'Product manager shipping payments roadmaps.',
        reason: 'Name the role.', evidence_status: 'supported', source: 'rules' },
      { section: 'skills', kind: 'add', original: null, suggested: 'Built LLM-powered features with RAG.',
        reason: 'Most asked-for gap.', evidence_status: 'add_only_if_true', source: 'rules' },
    ],
    corpus: { uk_jobs_scanned: 100 },
    ...over,
  };
}

const REVIEW_OK: ResumeReviewResponse = {
  available: true, detail: null, model: 'claude-test', summary: 'Solid base; lead with outcomes.',
  section_notes: [{ section: 'summary', note: 'Open with the AI PM title you are targeting.' }],
  suggestions: [], rejected_count: 0,
};

/** Seed the pickers and the two checker endpoints; returns the captured check request bodies. */
function seed(opts: { check?: ResumeCheckResponse; review?: ResumeReviewResponse } = {}) {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.get('/api/v1/skills/roles', () => HttpResponse.json(ROLES)),
    http.get('/api/v1/resumes/', () =>
      HttpResponse.json({ items: [{ id: 'r1', name: 'Suraj_AIPM.pdf', archived: false }], total: 1, archived_count: 0 })),
    http.post('/api/v1/resume-checker/check', async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(opts.check ?? checkBody());
    }),
    http.post('/api/v1/resume-checker/review', () => HttpResponse.json(opts.review ?? REVIEW_OK)),
  );
  return bodies;
}

function renderPage(path = '/resume-checker') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}><ResumeCheckerPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Wait for the résumé list (the select exists while it loads), then choose r1. */
async function pickResume() {
  await screen.findByRole('option', { name: 'Suraj_AIPM.pdf' });
  await userEvent.selectOptions(screen.getByLabelText('Résumé'), 'r1');
}

/** Choose the résumé and the first stored job, then run. */
async function runJobCheck() {
  await pickResume();
  const jobSelect = await screen.findByLabelText('Job to check against');
  await screen.findByRole('option', { name: /senior frontend engineer/i });
  await userEvent.selectOptions(jobSelect, 'job-1');
  await userEvent.click(screen.getByRole('button', { name: /run check/i }));
  await screen.findByText('Overall fit');
}

describe('ResumeCheckerPage', () => {
  it('renders the score, its components and the formula', async () => {
    const bodies = seed();
    renderPage();
    await runJobCheck();

    expect(screen.getByText('/100').parentElement).toHaveTextContent('64/100');
    expect(within(screen.getByRole('table', { name: /how the overall/i })).getByText('64')).toBeInTheDocument();
    expect(screen.getAllByText('Decent fit').length).toBeGreaterThan(0);
    const ledger = screen.getByRole('table', { name: /how the overall fit score is calculated/i });
    expect(within(ledger).getByText('Must-have skills')).toBeInTheDocument();
    expect(within(ledger).getByText('4 of 5 must-haves evidenced')).toBeInTheDocument();
    // weight × score × 100 = 0.5 × 0.8 × 100
    expect(within(ledger).getByText('40.0')).toBeInTheDocument();
    expect(screen.getByText(/0\.50 × must-have \+ 0\.20 × nice-to-have/)).toBeInTheDocument();
    expect(bodies[0]).toEqual({ resume_id: 'r1', job_id: 'job-1' });
  });

  it('quotes the résumé evidence for matched skills', async () => {
    seed();
    renderPage();
    await runJobCheck();
    const quote = screen.getByText('Owned the 12-month roadmap for the payments platform');
    expect(quote.tagName).toBe('Q');
    expect(screen.getByText(/from experience/i)).toBeInTheDocument();
  });

  it('lists missing skills in the given order with "N of M UK jobs"', async () => {
    seed();
    renderPage();
    await runJobCheck();
    const rows = screen.getAllByTestId('missing-skill');
    expect(rows.map((r) => within(r).getByText(/^(Generative AI|SQL|Figma)/).textContent))
      .toEqual(['Generative AI / LLMs', 'SQL', 'Figma']);
    expect(within(rows[0]!).getByText(/asked for in 42 of 100 uk jobs/i)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /must-haves/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /nice-to-haves/i })).toBeInTheDocument();
  });

  it('says "no UK job corpus yet" instead of a share when nothing was scanned', async () => {
    seed({ check: checkBody({ corpus: { uk_jobs_scanned: 0 } }) });
    renderPage();
    await runJobCheck();
    expect(screen.getAllByText(/no uk job corpus yet/i)).toHaveLength(3);
    expect(screen.queryByText(/of 0 uk jobs/i)).not.toBeInTheDocument();
  });

  it('marks only the add_only_if_true suggestion with "Add only if true"', async () => {
    seed();
    renderPage();
    await runJobCheck();
    const [supported, unverified] = screen.getAllByTestId('suggestion');
    expect(within(supported!).queryByText(/add only if true/i)).not.toBeInTheDocument();
    expect(within(supported!).getByText('Product person.')).toBeInTheDocument();
    expect(within(unverified!).getByText(/add only if true/i)).toBeInTheDocument();
    expect(within(unverified!).getByText(/include it only if it's genuinely true/i)).toBeInTheDocument();
  });

  it('merges AI section notes and AI suggestions once the review lands', async () => {
    seed({
      review: {
        ...REVIEW_OK,
        suggestions: [{ section: 'experience', kind: 'rewrite', original: 'Did stuff.', suggested: 'Shipped X.',
          reason: 'Lead with outcomes.', evidence_status: 'supported', source: 'llm' }],
      },
    });
    renderPage();
    await runJobCheck();
    const summary = screen.getByTestId('section-summary');
    expect(await within(summary).findByText('Open with the AI PM title you are targeting.')).toBeInTheDocument();
    expect(within(summary).getByText('Summary does not name the target role.')).toBeInTheDocument();
    expect(screen.getByText('Solid base; lead with outcomes.')).toBeInTheDocument();
    expect(screen.getByText('Shipped X.')).toBeInTheDocument();
  });

  it('shows the detail calmly when the AI review is unavailable', async () => {
    seed({ review: { available: false, detail: 'No Anthropic API key configured', section_notes: [], suggestions: [], rejected_count: 0 } });
    renderPage();
    await runJobCheck();
    expect(await screen.findByText(/ai review unavailable: no anthropic api key configured/i)).toBeInTheDocument();
    // The deterministic report is still there.
    expect(screen.getByText('Product roadmapping')).toBeInTheDocument();
  });

  it('role-target mode sends role_titles and no job_id', async () => {
    const bodies = seed({ check: checkBody({ target: { kind: 'roles', title: 'Skill Radar roles', role_titles: ['ML Engineer'] } }) });
    renderPage();
    await pickResume();
    await userEvent.click(screen.getByRole('radio', { name: /skill radar roles/i }));
    await userEvent.click(await screen.findByRole('button', { name: 'Clear all' }));
    await userEvent.click(await screen.findByRole('button', { name: 'ML Engineer' }));
    await userEvent.click(screen.getByRole('button', { name: /run check/i }));
    await screen.findByText('Overall fit');
    expect(bodies[0]).toEqual({ resume_id: 'r1', role_titles: ['ML Engineer'] });
    expect(bodies[0]).not.toHaveProperty('job_id');
  });

  it("shows the API's 422 sentence when no target is chosen", async () => {
    seed();
    server.use(
      http.post('/api/v1/resume-checker/check', () => HttpResponse.json(
        { detail: [{ loc: ['body'], msg: 'Value error, Give exactly one target: job_id, or a non-empty role_titles list.', type: 'value_error' }] },
        { status: 422 },
      )),
    );
    renderPage();
    await pickResume();
    await userEvent.click(screen.getByRole('button', { name: /run check/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Give exactly one target: job_id, or a non-empty role_titles list.');
  });

  it('preselects the résumé from ?resume=', async () => {
    seed();
    renderPage('/resume-checker?resume=r1');
    await screen.findByRole('option', { name: 'Suraj_AIPM.pdf' });
    await waitFor(() => expect(screen.getByLabelText('Résumé')).toHaveValue('r1'));
  });
});
