import { describe, it, expect } from 'vitest';

import { buildAppTimeline } from '@/lib/timeline';

describe('buildAppTimeline', () => {
  it('includes a "pending_review" step in review mode', () => {
    const steps = buildAppTimeline('review', 'queued');
    expect(steps.map((s) => s.key)).toContain('pending_review');
  });

  it('omits the "pending_review" step in autonomous mode', () => {
    const steps = buildAppTimeline('autonomous', 'queued');
    expect(steps.map((s) => s.key)).not.toContain('pending_review');
  });

  it('marks the current status step "current" and later steps "upcoming"', () => {
    const steps = buildAppTimeline('review', 'queued');
    const queued = steps.find((s) => s.key === 'queued');
    const applied = steps.find((s) => s.key === 'applied');
    expect(queued?.state).toBe('current');
    expect(applied?.state).toBe('upcoming');
  });

  it('marks steps before the current status as "done"', () => {
    const steps = buildAppTimeline('review', 'applied');
    expect(steps.find((s) => s.key === 'queued')?.state).toBe('done');
    expect(steps.find((s) => s.key === 'approved')?.state).toBe('done');
    expect(steps.find((s) => s.key === 'applied')?.state).toBe('current');
    expect(steps.find((s) => s.key === 'interview')?.state).toBe('upcoming');
  });

  it('describes the approved step by apply mode', () => {
    expect(buildAppTimeline('autonomous', 'applied').find((s) => s.key === 'approved')?.desc)
      .toMatch(/autonomous/i);
    expect(buildAppTimeline('batch', 'applied').find((s) => s.key === 'approved')?.desc)
      .toMatch(/batch/i);
    expect(buildAppTimeline('review', 'applied').find((s) => s.key === 'approved')?.desc)
      .toMatch(/by you/i);
  });

  it('marks the applying step "failed" and drops later steps for a failed run', () => {
    const steps = buildAppTimeline('autonomous', 'failed');
    const applying = steps.find((s) => s.key === 'applying');
    expect(applying?.state).toBe('failed');
    expect(steps.some((s) => s.key === 'applied')).toBe(false);
  });

  it('does not fabricate a diagnosis when the caller has no real one', () => {
    // Regression test: this used to hard-code "the agent couldn't locate the submit
    // button" for EVERY failure regardless of actual cause — a fake diagnosis shown
    // right next to the real one on AppDetailPage. No diagnosis argument means no
    // callout, not a guess.
    const steps = buildAppTimeline('autonomous', 'failed');
    expect(steps.find((s) => s.key === 'applying')?.diag).toBeUndefined();
  });

  it('surfaces the real diagnosis when the caller provides one', () => {
    const steps = buildAppTimeline('autonomous', 'failed', 'The LLM gateway timed out mid-run.');
    expect(steps.find((s) => s.key === 'applying')?.diag).toBe('The LLM gateway timed out mid-run.');
  });

  it('appends a terminal "Rejected" step after the reached progress for a rejected run', () => {
    const steps = buildAppTimeline('review', 'rejected');
    const last = steps[steps.length - 1];
    expect(last?.state).toBe('rejected');
    expect(last?.label).toMatch(/rejected/i);
    expect(steps.find((s) => s.key === 'applied')?.state).toBe('done');
  });

  it('appends a terminal "Withdrawn" step for a withdrawn run', () => {
    const steps = buildAppTimeline('batch', 'withdrawn');
    const last = steps[steps.length - 1];
    expect(last?.state).toBe('withdrawn');
    expect(last?.label).toMatch(/withdrawn/i);
  });

  it('marks the interview step current once an interview is reached', () => {
    const steps = buildAppTimeline('review', 'interview');
    expect(steps.find((s) => s.key === 'applied')?.state).toBe('done');
    expect(steps.find((s) => s.key === 'interview')?.state).toBe('current');
  });
});
