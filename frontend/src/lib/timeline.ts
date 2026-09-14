/** Application run timeline — ordered lifecycle steps with per-step state, derived from the
 *  application's apply mode + current status. Ported from the design prototype's `appTimeline()`.
 *  Pure and deterministic so it is unit-tested directly. */

export type TimelineState = 'done' | 'current' | 'upcoming' | 'failed' | 'rejected' | 'withdrawn';

export interface TimelineStep {
  key: string;
  label: string;
  desc: string;
  state: TimelineState;
  diag?: string;
}

export function buildAppTimeline(mode: string, status: string, diagnosis?: string): TimelineStep[] {
  const defs = [
    { key: 'queued', label: 'Queued', desc: 'Added to the apply queue' },
    { key: 'pending_review', label: 'Pending review', desc: 'Waiting for your approval' },
    {
      key: 'approved',
      label: 'Approved',
      desc:
        mode === 'autonomous'
          ? 'Auto-approved · autonomous mode'
          : mode === 'batch'
            ? 'Approved in a batch'
            : 'Approved by you',
    },
    { key: 'applying', label: 'Applying', desc: 'Agent submitting the application' },
    { key: 'applied', label: 'Applied', desc: 'Application submitted successfully' },
    { key: 'interview', label: 'Interview scheduled', desc: 'Recruiter reached out' },
    { key: 'offer', label: 'Offer received', desc: 'Congratulations — an offer landed' },
  ];

  // Review mode has an explicit approval gate; other modes skip it.
  const path = defs.filter((s) => (mode === 'review' ? true : s.key !== 'pending_review'));
  const order = path.map((s) => s.key);
  const idxOf = (k: string) => order.indexOf(k);
  const applyingIdx = idxOf('applying');

  let reachedIdx: number;
  let terminal: { label: string; desc: string; state: TimelineState } | null = null;
  if (status === 'rejected') {
    reachedIdx = idxOf('applied');
    terminal = { label: 'Rejected', desc: 'Employer passed after reviewing the application', state: 'rejected' };
  } else if (status === 'withdrawn') {
    reachedIdx = Math.max(idxOf('approved'), idxOf('queued'));
    terminal = { label: 'Withdrawn', desc: 'You withdrew this application', state: 'withdrawn' };
  } else if (status === 'failed') {
    reachedIdx = applyingIdx;
  } else {
    reachedIdx = idxOf(status);
  }

  const steps: TimelineStep[] = [];
  path.forEach((s, p) => {
    let state: TimelineState;
    if (status === 'failed') {
      if (p < applyingIdx) state = 'done';
      else if (p === applyingIdx) state = 'failed';
      else return;
    } else if (terminal) {
      if (p <= reachedIdx) state = 'done';
      else return;
    } else if (p < reachedIdx) {
      state = 'done';
    } else if (p === reachedIdx) {
      state = 'current';
    } else {
      state = 'upcoming';
    }

    const step: TimelineStep = { key: s.key, label: s.label, desc: s.desc, state };
    if (state === 'failed') {
      step.desc = '';
      // No fallback guess here: a wrong specific claim is worse than none. The caller
      // passes the real diagnosis when it has one (see AppDetailPage); a caller without
      // one — a list row, say — simply gets no callout rather than a fabricated cause.
      if (diagnosis) step.diag = diagnosis;
    }
    steps.push(step);
  });

  if (terminal) {
    steps.push({ key: terminal.state, label: terminal.label, desc: terminal.desc, state: terminal.state });
  }
  return steps;
}
