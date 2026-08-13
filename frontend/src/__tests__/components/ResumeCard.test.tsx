import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import ResumeCard from '@/components/resumes/ResumeCard';
import type { Resume } from '@/types/resume';

const resume = (o: Partial<Resume> = {}): Resume => ({
  id: 'r1', name: 'Alex Morgan — Senior PM', type: 'optimized', template_id: 'modern',
  base_resume_id: 'b1', job_id: null, has_pdf: true, has_docx: false, ats_score: 0.86,
  used_in_applications: 0, submitted_applications: 0, archived: false,
  created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-01T00:00:00Z', ...o,
});

const noop = () => {};

describe('ResumeCard', () => {
  it('shows the name, type badge, and ATS (0–1 scaled to percent)', () => {
    render(<ResumeCard resume={resume()} selected={false} onSelect={noop} onOptimize={noop} onDownload={noop} onDelete={noop} optimizing={false} deleting={false} />);
    expect(screen.getByText('Alex Morgan — Senior PM')).toBeInTheDocument();
    expect(screen.getByText('Optimized')).toBeInTheDocument();
    expect(screen.getByText('86')).toBeInTheDocument();
  });

  it('fires select, optimize, and download callbacks', async () => {
    const onSelect = vi.fn();
    const onOptimize = vi.fn();
    const onDownload = vi.fn();
    render(<ResumeCard resume={resume()} selected={false} onSelect={onSelect} onOptimize={onOptimize} onDownload={onDownload} onDelete={noop} optimizing={false} deleting={false} />);

    await userEvent.click(screen.getByRole('button', { name: /select résumé/i }));
    expect(onSelect).toHaveBeenCalledOnce();

    // The icon-only action buttons carry per-résumé accessible names ("Optimize résumé
    // <name>") rather than a bare "Optimize" — a résumé grid renders many cards, so a
    // duplicated bare label would leave screen-reader users unable to tell them apart.
    await userEvent.click(screen.getByRole('button', { name: /^optimize résumé/i }));
    expect(onOptimize).toHaveBeenCalledOnce();

    await userEvent.click(screen.getByRole('button', { name: /^download résumé/i }));
    expect(onDownload).toHaveBeenCalledOnce();
    expect(onSelect).toHaveBeenCalledOnce(); // inner buttons don't bubble to select
  });
});

describe('ResumeCard usage and removal', () => {
  it('states how many applications a CV has been sent with', () => {
    // The number decides whether removing it destroys a record, so it belongs where the
    // user is choosing rather than in the confirmation afterwards.
    render(
      <ResumeCard
        resume={resume({ used_in_applications: 3, submitted_applications: 2 })}
        selected={false} onSelect={noop} onOptimize={noop} onDownload={noop}
        onDelete={noop} optimizing={false} deleting={false}
      />,
    );
    expect(screen.getByText('Sent with 2 applications')).toBeInTheDocument();
  });

  it('distinguishes a CV attached only to drafts from one that has gone out', () => {
    render(
      <ResumeCard
        resume={resume({ used_in_applications: 1, submitted_applications: 0 })}
        selected={false} onSelect={noop} onOptimize={noop} onDownload={noop}
        onDelete={noop} optimizing={false} deleting={false}
      />,
    );
    expect(screen.getByText('Attached to 1 draft')).toBeInTheDocument();
  });

  it('says an unused CV is unused rather than leaving the line blank', () => {
    render(
      <ResumeCard
        resume={resume()} selected={false} onSelect={noop} onOptimize={noop}
        onDownload={noop} onDelete={noop} optimizing={false} deleting={false}
      />,
    );
    expect(screen.getByText('Not used yet')).toBeInTheDocument();
  });

  it('labels the button archive, not delete, once the CV has been sent', async () => {
    // The two outcomes differ and the user has to know which before clicking, not after.
    const onDelete = vi.fn();
    render(
      <ResumeCard
        resume={resume({ submitted_applications: 1 })}
        selected={false} onSelect={noop} onOptimize={noop} onDownload={noop}
        onDelete={onDelete} optimizing={false} deleting={false}
      />,
    );
    expect(screen.queryByRole('button', { name: /^delete résumé/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /archive résumé/i }));
    expect(onDelete).toHaveBeenCalledOnce();
  });

  it('labels the button delete when nothing has been sent', () => {
    render(
      <ResumeCard
        resume={resume()} selected={false} onSelect={noop} onOptimize={noop}
        onDownload={noop} onDelete={noop} optimizing={false} deleting={false}
      />,
    );
    expect(screen.getByRole('button', { name: /delete résumé/i })).toBeInTheDocument();
  });
});
