import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import SkillRadarPage from '@/pages/SkillRadarPage';

const ROLES = ['AI Product Manager', 'Product Manager', 'Product Analyst', 'Technical Product Manager', 'ML Engineer'];

function skill(key: string, label: string, over: Record<string, unknown> = {}) {
  return {
    key, label, category: 'Product craft', demand: 15, roles_wanting: 3,
    must_have: true, ats: true, corpus_count: null, ...over,
  };
}

function seed() {
  server.use(
    http.get('/api/v1/skills/roles', () => HttpResponse.json(ROLES)),
    http.get('/api/v1/resumes/', () =>
      HttpResponse.json({
        items: [{ id: 'r1', name: 'Suraj_AIPM.pdf', archived: false }],
        total: 1, archived_count: 0,
      }),
    ),
    http.post('/api/v1/skills/aggregate', () =>
      HttpResponse.json({
        titles: ['AI Product Manager'],
        categories: ['Product craft', 'AI / ML'],
        corpus_used: true,
        skills: [
          skill('roadmap', 'Product roadmapping', { demand: 20, roles_wanting: 4, corpus_count: 180 }),
          skill('genai', 'Generative AI / LLMs', { category: 'AI / ML', demand: 10, roles_wanting: 2, must_have: true }),
        ],
      }),
    ),
    http.post('/api/v1/skills/score', () =>
      HttpResponse.json({
        resume_id: 'r1', resume_name: 'Suraj_AIPM.pdf', titles: ['AI Product Manager'],
        score: 0.63, must_have_score: 0.8, band: 'decent', matched_count: 12, total_count: 20,
        hits: [
          { key: 'roadmap', label: 'Product roadmapping', category: 'Product craft', demand: 20, roles_wanting: 4, must_have: true, ats: true, present: true, matched_form: 'roadmap' },
          { key: 'genai', label: 'Generative AI / LLMs', category: 'AI / ML', demand: 10, roles_wanting: 2, must_have: true, ats: true, present: false, matched_form: null },
        ],
        top_to_add: [
          { key: 'genai', label: 'Generative AI / LLMs', category: 'AI / ML', demand: 10, roles_wanting: 2, must_have: true, ats: true, present: false, matched_form: null },
        ],
      }),
    ),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><SkillRadarPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SkillRadarPage', () => {
  it('shows the aggregated in-demand skills for the default role selection', async () => {
    seed();
    renderPage();
    // Pre-seeded with a product cluster, so demand renders without any interaction.
    expect(await screen.findByText('Product roadmapping')).toBeInTheDocument();
    expect(screen.getByText('Generative AI / LLMs')).toBeInTheDocument();
    // Live-corpus enrichment is surfaced.
    expect(screen.getByText(/enriched from your stored jobs/i)).toBeInTheDocument();
  });

  it('scores the chosen résumé and reads it against the 60–70% band', async () => {
    seed();
    renderPage();
    await screen.findByText('Product roadmapping');

    await userEvent.selectOptions(await screen.findByLabelText(/choose a résumé to score/i), 'r1');
    await userEvent.click(screen.getByRole('button', { name: /run match/i }));

    // The headline score and the "decent" band both show.
    expect(await screen.findByText('63%')).toBeInTheDocument();
    expect(screen.getByText(/decent - most covered/i)).toBeInTheDocument();
    // The top gap is surfaced as something to add.
    expect(screen.getByText(/add these next/i)).toBeInTheDocument();
  });

  it('selecting a role clears a prior score (it was against different roles)', async () => {
    seed();
    renderPage();
    await screen.findByText('Product roadmapping');
    await userEvent.selectOptions(await screen.findByLabelText(/choose a résumé/i), 'r1');
    await userEvent.click(screen.getByRole('button', { name: /run match/i }));
    await screen.findByText('63%');

    // Toggle a role off — the stale score must disappear.
    await userEvent.click(screen.getByRole('button', { name: 'ML Engineer' }));
    await waitFor(() => expect(screen.queryByText('63%')).not.toBeInTheDocument());
  });

  it('guides the user when they have no résumés to score', async () => {
    seed();
    server.use(
      http.get('/api/v1/resumes/', () =>
        HttpResponse.json({ items: [], total: 0, archived_count: 0 })),
    );
    renderPage();
    expect(await screen.findByText(/upload a résumé on the résumés page first/i)).toBeInTheDocument();
  });
});
