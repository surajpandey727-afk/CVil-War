import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import EvidencePanel from '@/components/applications/EvidencePanel';
import type { ApplicationEvidence } from '@/types/evidence';

const full = (overrides: Partial<ApplicationEvidence> = {}): ApplicationEvidence => ({
  application_id: 'app-1',
  job: {
    recorded: true, job_id: 'job-1', title: 'Senior Product Manager', company: 'Zartis',
    location: 'London, UK', salary: '£75,000 - £95,000', remote: false, source: 'reed',
    job_url: 'https://www.reed.co.uk/jobs/senior-product-manager/56654149',
    application_url: null, posted_at: null,
  },
  submission: {
    status: 'applied', method: 'automated', confirmation_state: 'confirmed',
    confirmation_detail: 'Application submitted — reference REED-88213',
    external_reference: 'REED-88213', submitted_at: '2026-08-13T21:05:00Z',
    ats_score: 0.72, apply_mode: 'review', origin: 'discovery', actor: 'agent', recorded: true,
  },
  resume: {
    recorded: true, document_id: 'resume-1', name: 'AI Product Manager CV', kind: 'tailored',
    ats_score: 0.88, created_at: '2026-08-12T10:00:00Z', archived: false,
    has_pdf: true, has_docx: false,
  },
  cover_letter: { recorded: true, used: true, name: 'zartis-cl-v2.pdf', origin: 'generated' },
  account: {
    recorded: true, platform: 'reed', account: 'sur***@example.com', connected: true,
    state: 'session_active', detail: null, last_used_at: null,
  },
  failure: null,
  log: [
    { at: '2026-08-13T21:04:12Z', source: 'application', kind: 'discovered', message: 'Job discovered', detail: null, actor: 'system' },
    { at: '2026-08-13T21:05:05Z', source: 'automation', kind: 'step_1', message: 'Submission confirmation detected', detail: null, actor: 'agent' },
  ],
  log_recorded: true,
  ...overrides,
});

function renderPanel(evidence: ApplicationEvidence | undefined, props: Partial<{ onRetry: () => void; onOpenResume: () => void; isLoading: boolean; isError: boolean }> = {}) {
  return render(
    <EvidencePanel
      evidence={evidence}
      isLoading={props.isLoading ?? false}
      isError={props.isError ?? false}
      retrying={false}
      onRetry={props.onRetry ?? vi.fn()}
      onOpenResume={props.onOpenResume ?? vi.fn()}
    />,
  );
}

describe('EvidencePanel', () => {
  it('answers "applied where, with what, through which account"', () => {
    renderPanel(full());

    expect(screen.getByText('Senior Product Manager')).toBeInTheDocument();
    expect(screen.getByText(/Zartis · London, UK/)).toBeInTheDocument();
    expect(screen.getByText('AI Product Manager CV')).toBeInTheDocument();
    expect(screen.getByText('zartis-cl-v2.pdf')).toBeInTheDocument();
    // Twice on purpose: once as the board the job came from, once as the account the
    // submission went through. They are separate facts that happen to agree here, and a
    // single lookup would hide the case where they disagree.
    expect(screen.getAllByText('reed')).toHaveLength(2);
    expect(screen.getByText('sur***@example.com')).toBeInTheDocument();
    expect(screen.getByText('REED-88213')).toBeInTheDocument();
  });

  it('opens the real stored job URL', () => {
    // Never constructed. The href has to be the value the backend stored, or the button is
    // a guess dressed up as a fact.
    renderPanel(full());

    const link = screen.getByRole('link', { name: /open job/i });
    expect(link).toHaveAttribute(
      'href',
      'https://www.reed.co.uk/jobs/senior-product-manager/56654149',
    );
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('says the job URL is unavailable rather than rendering a dead button', () => {
    const evidence = full();
    evidence.job.job_url = null;
    renderPanel(evidence);

    expect(screen.queryByRole('link', { name: /open job/i })).not.toBeInTheDocument();
    expect(screen.getByText(/job url unavailable/i)).toBeInTheDocument();
  });

  it('offers a separate application link only when one genuinely exists', () => {
    renderPanel(full());
    expect(screen.queryByRole('link', { name: /open application/i })).not.toBeInTheDocument();

    const evidence = full();
    evidence.job.application_url = 'https://apply.zartis.com/form/9910';
    renderPanel(evidence);
    expect(screen.getByRole('link', { name: /open application/i })).toHaveAttribute(
      'href', 'https://apply.zartis.com/form/9910',
    );
  });

  it('distinguishes a confirmed submission from a simulated one', () => {
    // The core claim of the product. A run with live apply off sent nothing to anybody, and
    // must never read the same as a submission an employer acknowledged.
    renderPanel(full());
    expect(screen.getByText('Confirmed')).toBeInTheDocument();

    const simulated = full();
    simulated.submission.confirmation_state = 'simulated';
    simulated.submission.method = 'simulated';
    renderPanel(simulated);

    expect(screen.getByText('Simulated')).toBeInTheDocument();
    expect(screen.getByText(/no browser ran and nothing was sent/i)).toBeInTheDocument();
  });

  it('distinguishes a run that finished from one that was acknowledged', () => {
    const unconfirmed = full();
    unconfirmed.submission.confirmation_state = 'unconfirmed';
    renderPanel(unconfirmed);

    expect(screen.getByText('Not confirmed')).toBeInTheDocument();
    expect(screen.getByText(/nothing corroborated that it was received/i)).toBeInTheDocument();
  });

  it('prints "Not recorded" for anything that was never captured', () => {
    // Historical applications have no method and no account. A blank field reads as fact;
    // an explicit admission does not.
    const sparse = full();
    sparse.submission.method = null;
    sparse.submission.external_reference = null;
    renderPanel(sparse);

    expect(screen.getAllByText('Not recorded').length).toBeGreaterThanOrEqual(2);
  });

  it('states when no CV, no letter, no account and no log were recorded', () => {
    const empty = full({
      resume: { recorded: false, document_id: null, name: null, kind: null, ats_score: null, created_at: null, archived: false, has_pdf: false, has_docx: false },
      cover_letter: { recorded: true, used: false, name: null, origin: null },
      account: { recorded: false, platform: null, account: null, connected: false, state: null, detail: null, last_used_at: null },
      log: [],
      log_recorded: false,
    });
    renderPanel(empty);

    expect(screen.getByText(/no cv was attached/i)).toBeInTheDocument();
    expect(screen.getByText(/no cover letter used/i)).toBeInTheDocument();
    expect(screen.getByText(/no account was recorded/i)).toBeInTheDocument();
    expect(screen.getByText(/no execution history was recorded/i)).toBeInTheDocument();
  });

  it('keeps naming an archived CV and says why it is still there', () => {
    const evidence = full();
    evidence.resume.archived = true;
    renderPanel(evidence);

    expect(screen.getByText(/archived, kept for this record/)).toBeInTheDocument();
  });

  it('shows the real run log, both lifecycle and automation entries', () => {
    renderPanel(full());

    expect(screen.getByText('Job discovered')).toBeInTheDocument();
    expect(screen.getByText('Submission confirmation detected')).toBeInTheDocument();
  });

  it('expands a long log rather than truncating it silently', async () => {
    const evidence = full({
      log: Array.from({ length: 12 }, (_, i) => ({
        at: `2026-08-13T21:0${i % 10}:00Z`,
        source: 'automation',
        kind: `step_${i}`,
        message: `Step number ${i}`,
        detail: null,
        actor: 'agent',
      })),
      log_recorded: true,
    });
    renderPanel(evidence);

    expect(screen.queryByText('Step number 0')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /view full log \(12\)/i }));
    expect(screen.getByText('Step number 0')).toBeInTheDocument();
  });

  describe('failures', () => {
    const failed = () =>
      full({
        failure: {
          message: 'Required field "Work Authorisation" was not accepted.',
          failure_class: 'form_rejection',
          root_cause: 'The portal rejected the answer supplied for work authorisation.',
          failed_at: '2026-08-13T21:05:00Z',
          url: 'https://apply.zartis.com/form/9910',
          step_count: 11,
          can_retry: true,
        },
      });

    it('shows the stage, reason and where it happened', () => {
      renderPanel(failed());

      expect(screen.getByText(/Work Authorisation/)).toBeInTheDocument();
      expect(screen.getByText(/portal rejected the answer/i)).toBeInTheDocument();
      expect(screen.getByText('form_rejection')).toBeInTheDocument();
      expect(screen.getByText('https://apply.zartis.com/form/9910')).toBeInTheDocument();
      expect(screen.getByText('11')).toBeInTheDocument();
    });

    it('offers a retry that actually calls back', async () => {
      const onRetry = vi.fn();
      renderPanel(failed(), { onRetry });

      await userEvent.click(screen.getByRole('button', { name: /retry application/i }));
      expect(onRetry).toHaveBeenCalledOnce();
    });

    it('hides the retry when the backend says re-queueing is not supported', () => {
      // A button that does nothing is worse than no button.
      const evidence = failed();
      evidence.failure!.can_retry = false;
      renderPanel(evidence);

      expect(screen.queryByRole('button', { name: /retry application/i })).not.toBeInTheDocument();
    });

    it('shows no failure section for a healthy application', () => {
      renderPanel(full());
      expect(screen.queryByText(/retry application/i)).not.toBeInTheDocument();
    });
  });

  it('distinguishes a load failure from an application with nothing recorded', () => {
    renderPanel(undefined, { isError: true });

    expect(screen.getByText(/evidence could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/still stored/i)).toBeInTheDocument();
  });

  it('opens the résumé through the caller', async () => {
    const onOpenResume = vi.fn();
    renderPanel(full(), { onOpenResume });

    await userEvent.click(screen.getByRole('button', { name: /view résumé/i }));
    expect(onOpenResume).toHaveBeenCalledOnce();
  });
});
