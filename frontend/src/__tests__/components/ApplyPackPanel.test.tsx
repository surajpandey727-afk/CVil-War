import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { server } from '@/__tests__/mocks/server';
import ApplyPackPanel from '@/components/applications/ApplyPackPanel';
import type { ApplyPack } from '@/types/applyPack';

const PACK: ApplyPack = {
  application_id: 'a1', job_title: 'Senior PM', company: 'Monzo',
  employer_url: 'https://monzo.example/jobs/1', location: 'London',
  manual_reason: 'Automatic submission is off on this deployment, so this one is yours to send.',
  cv: { name: 'alex.pdf', download_path: '/api/v1/resumes/r1/download?format=pdf' },
  has_cover_letter: false, fit_overall: 0.72,
  answers: [
    { question: 'Full name', answer: 'Alex Morgan', evidence_status: 'supported', note: '' },
    { question: 'Do you have the right to work in the UK?', answer: '[Add only if true]', evidence_status: 'add_only_if_true', note: 'Only you can answer this; it is never inferred.' },
  ],
  checklist: ["Open the employer's application page (link above).", 'Attach the CV shown above.'],
};

function renderPanel(pack: ApplyPack | null) {
  server.use(
    http.get('/api/v1/applications/a1/pack', () =>
      pack ? HttpResponse.json(pack) : HttpResponse.json({ detail: 'boom' }, { status: 500 })),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><ApplyPackPanel applicationId="a1" /></QueryClientProvider>);
}

describe('ApplyPackPanel', () => {
  it('shows the employer link, the CV and the checklist', async () => {
    renderPanel(PACK);
    const link = await screen.findByRole('link', { name: /Open employer page/ });
    expect(link).toHaveAttribute('href', 'https://monzo.example/jobs/1');
    expect(screen.getByRole('button', { name: /Download CV \(alex.pdf\)/ })).toBeInTheDocument();
    expect(screen.getByText('fit 72/100')).toBeInTheDocument();
    expect(screen.getByText('Attach the CV shown above.')).toBeInTheDocument();
  });

  it('marks unverifiable answers "add only if true" and not verified ones', async () => {
    renderPanel(PACK);
    await screen.findByText('Alex Morgan');
    const markers = screen.getAllByText('ADD ONLY IF TRUE');
    expect(markers).toHaveLength(1);
    expect(screen.getByText('Only you can answer this; it is never inferred.')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Copy' })).toHaveLength(2);
  });

  it('says so when the pack cannot be prepared', async () => {
    renderPanel(null);
    expect(await screen.findByText(/Couldn.t prepare the pack/)).toBeInTheDocument();
  });
});
