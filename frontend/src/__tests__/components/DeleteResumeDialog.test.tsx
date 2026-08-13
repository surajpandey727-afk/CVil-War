import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { server } from '@/__tests__/mocks/server';
import DeleteResumeDialog from '@/components/resumes/DeleteResumeDialog';
import type { Resume } from '@/types/resume';

const resume = (o: Partial<Resume> = {}): Resume => ({
  id: 'r1', name: 'Suraj_Pandey_AIPM.pdf', type: 'base', template_id: 'modern',
  base_resume_id: null, job_id: null, has_pdf: true, has_docx: false, ats_score: 0.82,
  used_in_applications: 0, submitted_applications: 0, archived: false,
  created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-01T00:00:00Z', ...o,
});

function renderDialog(r: Resume, onConfirm = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <DeleteResumeDialog resume={r} busy={false} onConfirm={onConfirm} onCancel={vi.fn()} />
    </QueryClientProvider>,
  );
  return onConfirm;
}

function usage(items: Array<Record<string, unknown>>) {
  const submitted = items.filter((i) => i['submitted']).length;
  server.use(
    http.get('/api/v1/resumes/:resumeId/usage', () =>
      HttpResponse.json({ resume_id: 'r1', total: items.length, submitted, items }),
    ),
  );
}

describe('DeleteResumeDialog', () => {
  it('offers a permanent delete for a CV that has never been sent', async () => {
    renderDialog(resume());

    // The heading resolves immediately from the card's own counter, but the body waits for
    // the live usage check — awaiting the heading alone would assert against the interim
    // "checking where it has been used…" state.
    expect(await screen.findByText(/never been sent to an employer/i)).toBeInTheDocument();
    expect(screen.getByText(/delete this cv\?/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete permanently/i })).toBeInTheDocument();
  });

  it('offers an archive instead once the CV has reached an employer', async () => {
    // The distinction is the whole point of the dialog: hard-deleting a used CV would blank
    // `applications.resume_id` through ON DELETE SET NULL and destroy the record of what was
    // received, silently and permanently.
    usage([
      { application_id: 'a1', job_title: 'Product Manager', company: 'Wise', status: 'applied', submitted: true, applied_at: null, ats_score: 0.8 },
    ]);
    renderDialog(resume({ submitted_applications: 1 }));

    expect(await screen.findByText(/archive this cv\?/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /archive it/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete permanently/i })).not.toBeInTheDocument();
  });

  it('names the applications that used it rather than only counting them', async () => {
    usage([
      { application_id: 'a1', job_title: 'Product Manager', company: 'Wise', status: 'applied', submitted: true, applied_at: null, ats_score: null },
      { application_id: 'a2', job_title: 'Group PM', company: 'Monzo', status: 'queued', submitted: false, applied_at: null, ats_score: null },
    ]);
    renderDialog(resume({ submitted_applications: 1 }));

    expect(await screen.findByText(/Product Manager/)).toBeInTheDocument();
    expect(screen.getByText(/Group PM/)).toBeInTheDocument();
    // "sent" and "queued" are different facts about the same CV and the user is deciding on
    // the strength of that difference.
    expect(screen.getByText('sent')).toBeInTheDocument();
    expect(screen.getByText('queued')).toBeInTheDocument();
  });

  it('does not offer an archive just because a draft references the CV', async () => {
    // A queued application has not been sent anywhere. Protecting a CV for its sake would
    // make every experiment permanent.
    usage([
      { application_id: 'a2', job_title: 'Group PM', company: 'Monzo', status: 'queued', submitted: false, applied_at: null, ats_score: null },
    ]);
    renderDialog(resume({ used_in_applications: 1, submitted_applications: 0 }));

    expect(await screen.findByText(/delete this cv\?/i)).toBeInTheDocument();
  });

  it('confirms with the caller', async () => {
    const onConfirm = renderDialog(resume());
    await userEvent.click(await screen.findByRole('button', { name: /delete permanently/i }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
