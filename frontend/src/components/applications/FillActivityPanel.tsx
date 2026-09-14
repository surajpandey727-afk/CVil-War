import { useEffect, useRef } from 'react';

import Icon from '@/components/ui/Icon';
import { useAppStore } from '@/store/useAppStore';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

/**
 * The live, step-by-step "what is the browser doing right now" feed for one application —
 * distinct from the Run timeline (lifecycle: queued/applying/applied) and the Evidence panel's
 * Run log (the finished run's persisted history). This is neither: it is
 * `core.automation.runtime.observe.make_step_observer`'s per-step WebSocket event, which
 * previously reached the frontend and was thrown away (only used to invalidate a query).
 *
 * Only rendered while there is something to show — a run that has never gone live leaves no
 * steps behind, and this must not be mistaken for "the agent did nothing".
 */
export default function FillActivityPanel({ applicationId, isApplying }: {
  applicationId: string;
  isApplying: boolean;
}) {
  const steps = useAppStore((s) => s.fillActivity[applicationId]);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el && typeof el.scrollTo === 'function') el.scrollTo({ top: el.scrollHeight });
  }, [steps?.length]);

  if (!steps || steps.length === 0) return null;

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ position: 'relative', width: 8, height: 8, borderRadius: '50%', background: isApplying ? 'var(--accent)' : 'var(--text-4)' }}>
          {isApplying && (
            <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: 'var(--accent)', animation: 'aaPulse 1.4s var(--ease-io) infinite' }} />
          )}
        </span>
        <span style={{ font: '700 13px/1 var(--font)' }}>
          {isApplying ? 'Filling the form, live' : 'Fill activity'}
        </span>
        <span style={{ marginLeft: 'auto', font: '600 10px/1 var(--mono)', color: 'var(--text-4)' }}>
          {steps.length} STEP{steps.length === 1 ? '' : 'S'}
        </span>
      </div>
      <div
        ref={listRef}
        style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 220, overflowY: 'auto' }}
      >
        {steps.map((step, i) => (
          <div key={i} style={{ display: 'flex', gap: 9, alignItems: 'baseline' }}>
            <span style={{ flex: '0 0 auto', font: '600 10.5px/1.5 var(--mono)', color: 'var(--text-4)' }}>
              {new Date(step.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
            <span style={{ flex: '1 1 auto', minWidth: 0, font: '500 11.5px/1.5 var(--mono)', color: 'var(--text-2)' }}>
              {step.detail}
            </span>
          </div>
        ))}
      </div>
      {!isApplying && (
        <p style={{ margin: '10px 0 0', font: '500 11px/1.4 var(--font)', color: 'var(--text-4)' }}>
          <Icon name="check" size={11} /> Run finished — this is what streamed in live while it ran.
        </p>
      )}
    </div>
  );
}
