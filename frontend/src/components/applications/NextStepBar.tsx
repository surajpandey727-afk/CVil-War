/**
 * The bottom line of an application row: what it is waiting for, and the way forward.
 *
 * There is always a way forward. Automated submission needs the automation host and (for
 * some boards) a signed-in session; when either is missing the owner can still apply on the
 * employer's page and record it here, which marks it applied as a manual, confirmed
 * submission — never as an automated one.
 */
import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import { useApproveApplication, useResolveBlocker, useUpdateApplicationStatus } from '@/hooks/useApplications';
import { HOST_COMMAND, type NextStep } from '@/lib/applyNextStep';
import { useAppStore } from '@/store/useAppStore';
import type { Application } from '@/types/application';

const TONE: Record<NextStep['kind'], { color: string; soft: string; icon: 'alert' | 'clock' | 'refresh' | 'bookmark' }> = {
  approve: { color: 'var(--review)', soft: 'var(--review-soft)', icon: 'alert' },
  verify: { color: 'var(--review)', soft: 'var(--review-soft)', icon: 'alert' },
  sign_in: { color: 'var(--review)', soft: 'var(--review-soft)', icon: 'alert' },
  host: { color: 'var(--text-2)', soft: 'var(--surface-2)', icon: 'clock' },
  hold: { color: 'var(--text-2)', soft: 'var(--surface-2)', icon: 'clock' },
  running: { color: 'var(--accent)', soft: 'var(--accent-soft)', icon: 'refresh' },
  none: { color: 'var(--text-3)', soft: 'transparent', icon: 'bookmark' },
};

const btn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 11px',
  borderRadius: 'var(--r-md)', border: '1px solid var(--border-2)', background: 'var(--surface)',
  color: 'var(--text-2)', font: '600 11.5px/1 var(--font)', cursor: 'pointer', textDecoration: 'none',
};

export default function NextStepBar({ app, step, onConnect, showApprove = false }: {
  app: Application; step: NextStep; onConnect: () => void;
  /** The list rows have their own Approve button; the application page does not. */
  showApprove?: boolean;
}) {
  const notify = useAppStore((s) => s.showNotification);
  const update = useUpdateApplicationStatus();
  const approve = useApproveApplication();
  const resume = useResolveBlocker();
  const [copied, setCopied] = useState(false);
  if (step.kind === 'none') return null;
  const tone = TONE[step.kind];

  const markApplied = () => {
    if (!window.confirm(`Mark "${app.job_title ?? 'this role'}" as applied by you? Only do this once you have actually submitted it on the employer's site.`)) return;
    update.mutate(
      { appId: app.id, update: { status: 'applied' } },
      {
        onSuccess: () => notify('Recorded as applied by you', 'success'),
        onError: () => notify('Could not record it — try again', 'error'),
      },
    );
  };

  const copyCommand = () => {
    void navigator.clipboard?.writeText(HOST_COMMAND).then(() => setCopied(true), () => undefined);
  };

  return (
    <div
      data-next-step={step.kind}
      style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginTop: 11, padding: '10px 12px', borderRadius: 'var(--r-md)', background: tone.soft, flexWrap: 'wrap' }}
    >
      <span style={{ color: tone.color, marginTop: 1, flex: '0 0 auto' }}><Icon name={tone.icon} size={14} /></span>
      <div style={{ flex: '1 1 260px', minWidth: 0 }}>
        <div style={{ font: '700 12px/1.35 var(--font)', color: 'var(--text)' }}>{step.headline}</div>
        {step.detail && (
          <div style={{ marginTop: 3, font: '500 11.5px/1.45 var(--font)', color: 'var(--text-3)', overflowWrap: 'anywhere' }}>{step.detail}</div>
        )}
      </div>
      {/* Shrinks and wraps: a non-shrinking group overflowed phone widths by ~120px. */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: '0 1 auto', minWidth: 0, maxWidth: '100%' }}>
        {step.kind === 'verify' && (
          <button
            type="button"
            disabled={resume.isPending}
            onClick={() => resume.mutate(app.id, {
              onSuccess: () => notify('Queued — a browser window opens on your PC for the check', 'success'),
              onError: () => notify('Could not resume it — try again', 'error'),
            })}
            style={{ ...btn, background: 'var(--accent)', borderColor: 'var(--accent)', color: 'var(--accent-ink)', fontWeight: 700 }}
          >
            Resume in a visible window
          </button>
        )}
        {showApprove && step.kind === 'approve' && (
          <button
            type="button"
            disabled={approve.isPending}
            onClick={() => approve.mutate(app.id, {
              onSuccess: () => notify('Approved — it goes out when the automation host picks it up', 'success'),
              onError: () => notify('Could not approve it — try again', 'error'),
            })}
            style={{ ...btn, background: 'var(--accent)', borderColor: 'var(--accent)', color: 'var(--accent-ink)', fontWeight: 700 }}
          >
            Approve
          </button>
        )}
        {step.kind === 'sign_in' && step.platform && (
          <button type="button" onClick={onConnect} style={{ ...btn, background: 'var(--accent)', borderColor: 'var(--accent)', color: 'var(--accent-ink)', fontWeight: 700 }}>
            Connect {step.platform.label}
          </button>
        )}
        {step.kind === 'host' && (
          <button type="button" onClick={copyCommand} title={`Copy: ${HOST_COMMAND}`} style={btn}>
            {copied ? 'Copied' : 'Copy start command'}
          </button>
        )}
        {app.application_url && (
          <a href={app.application_url} target="_blank" rel="noreferrer" style={btn} title="Open the posting to apply yourself">
            Open posting <Icon name="ext" size={11} />
          </a>
        )}
        {step.kind !== 'running' && (
          <button type="button" onClick={markApplied} disabled={update.isPending} style={btn} title="You applied on the employer's site — record it here">
            I applied myself
          </button>
        )}
      </div>
    </div>
  );
}
