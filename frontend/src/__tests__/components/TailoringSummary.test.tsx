import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import TailoringSummary from '@/components/resumes/TailoringSummary';
import type { AtsEvaluation, TailoringAudit } from '@/types/resume';

const evaluation = (ats: number, extra: Partial<AtsEvaluation> = {}): AtsEvaluation => ({
  ats_match: ats, parsing: 97, shortlist: 71, band: 'Moderate alignment', shortlist_band: 'Moderate alignment',
  components: {}, tiers: { critical: { matched: 4, mentioned: 1, total: 6 }, nice_to_have: { matched: 0, mentioned: 0, total: 0 } },
  strongest: [], weak: [], missing: [], problems: [],
  recruiter: { signal: 'Mixed', reasons: [] },
  verdict: { ats_alignment: 'Moderate', human_review: 'Moderate', why: [], holding_back: ["No evidence of 'sql' (critical)."], tailoring_limit: '' },
  parsing_findings: [], constrained_by: [], ...extra,
});

const audit = (extra: Partial<TailoringAudit> = {}): TailoringAudit => ({
  generation_status: 'generated', original_ats_score: 58, final_ats_score: 66, keywords_added: [], keywords_not_added: [],
  changes: [], rejected_edits: [], ...extra,
});

describe('TailoringSummary: the honest breakdown', () => {
  it('shows parsing, shortlist readiness and what is evidenced, with before → after', () => {
    render(<TailoringSummary audit={audit({ evaluation_before: evaluation(58), evaluation_after: evaluation(66), ats_target: 82, ats_target_reached: false, ats_target_note: 'The posting asks for SQL and there is no evidence of it.' })} />);
    const box = screen.getByTestId('match-breakdown');
    expect(box).toHaveTextContent('58 → 66');
    expect(box).toHaveTextContent('File parsing');
    expect(box).toHaveTextContent('Critical 4/6');
    expect(box).toHaveTextContent("No evidence of 'sql'");
  });

  it('says plainly when the target was not reached and why', () => {
    render(<TailoringSummary audit={audit({ evaluation_after: evaluation(66), ats_target: 82, ats_target_reached: false, ats_target_note: 'Adding SQL would be fabrication.' })} />);
    expect(screen.getByTestId('match-breakdown')).toHaveTextContent('Target 82 not reached. Adding SQL would be fabrication.');
  });

  it('does not nag when the target was reached', () => {
    render(<TailoringSummary audit={audit({ evaluation_after: evaluation(85), ats_target: 82, ats_target_reached: true, ats_target_note: '' })} />);
    expect(screen.getByTestId('match-breakdown')).not.toHaveTextContent('not reached');
  });
});

describe('TailoringSummary: suppressed bullets', () => {
  it('shows a removed bullet as removed, not as an empty edit', () => {
    render(<TailoringSummary audit={audit({
      changes: [{ line_id: 'L1', section: 'WORK', before_text: 'Managed 2 marketing automation products.', after_text: '', change_type: 'removed', reason: 'Removed: it adds least to this job.', evidence: 'x', keywords_added: [] }],
      pagination: { status: 'suppressed', before: { pages: 3, ok: false, rules: [] }, after: { pages: 3, ok: true, rules: [] } },
    })} />);
    expect(screen.getByText('Removed from this version')).toBeInTheDocument();
    expect(screen.getByText('Managed 2 marketing automation products.')).toBeInTheDocument();
    expect(screen.getByTestId('pagination-rules')).toHaveTextContent('Removed the bullets that add least to this job');
  });
});

describe('TailoringSummary: page layout rules', () => {
  const rules = (ok: boolean) => [
    { rule: 'education_and_work_same_page', ok, applicable: true, detail: 'Education is on page(s) [2] and Work on page(s) [2, 3].' },
    { rule: 'extra_curricular_new_page', ok: true, applicable: true, detail: '' },
    { rule: 'no_blank_pages', ok: true, applicable: false, detail: '' },
  ];

  it('lists each applicable rule and the reason one failed', () => {
    render(<TailoringSummary audit={audit({ pagination: { status: 'not_met', deficit_points: 144, before: { pages: 3, ok: false, rules: rules(false) } } })} />);
    const box = screen.getByTestId('pagination-rules');
    expect(box).toHaveTextContent('Page layout rules not fully met · 3 pages');
    expect(box).toHaveTextContent('✗ Education and Work on one page');
    expect(box).toHaveTextContent('✓ Extra-Curricular starts a new page');
    expect(box).not.toHaveTextContent('No blank pages');
    expect(box).toHaveTextContent('overflow one page by about 144pt');
    expect(box).toHaveTextContent('removing content, which was not done');
  });

  it('reports a re-flow as moving content without changing wording', () => {
    render(<TailoringSummary audit={audit({ pagination: { status: 'reflowed', before: { pages: 1, ok: false, rules: rules(false) }, after: { pages: 2, ok: true, rules: rules(true) } } })} />);
    expect(screen.getByTestId('pagination-rules')).toHaveTextContent('Re-flowed to meet the page layout rules (no wording changed) · 2 pages');
  });
});
