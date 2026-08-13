import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

import CompanyLogo from '@/components/ui/CompanyLogo';
import Icon from '@/components/ui/Icon';
import { useApplications, useApproveApplication, useBulkApprove } from '@/hooks/useApplications';
import { useApplicationEvents } from '@/hooks/useApplicationEvents';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useAppStore } from '@/store/useAppStore';
import { atsColor, atsPercent, relativeTime, statusMeta } from '@/lib/status';
import { buildAppTimeline, type TimelineState } from '@/lib/timeline';
import type { Application } from '@/types/application';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

/** Statuses that mean "this application is still moving". */
const ACTIVE = new Set(['queued', 'pending_review', 'approved', 'applying']);

const STEP_COLOR: Record<TimelineState, string> = {
  done: 'var(--offer)',
  current: 'var(--accent)',
  upcoming: 'var(--text-4)',
  failed: 'var(--failed)',
  rejected: 'var(--rejected)',
  withdrawn: 'var(--withdrawn)',
};

/**
 * Live run console.
 *
 * Reads the real application list and re-renders on `application_progress` — the same
 * WebSocket the rest of the app already listens to, so there is no second source of truth for
 * status. The per-application step strip comes from `buildAppTimeline`, which is the function
 * the detail-page timeline uses; the console is a compact many-rows view of the same data.
 */
export default function RunConsolePage() {
  const navigate = useNavigate();
  const notify = useAppStore((s) => s.showNotification);
  const intervention = useAppStore((s) => s.pendingIntervention);

  const { lastMessage, connected } = useWebSocket();
  useApplicationEvents(lastMessage);

  const { data, isLoading } = useApplications(1, 100);
  const approve = useApproveApplication();
  const bulkApprove = useBulkApprove();

  const apps = useMemo(() => data?.items ?? [], [data]);
  const active = useMemo(() => apps.filter((a) => ACTIVE.has(a.status)), [apps]);
  const recentlyDone = useMemo(
    () => apps.filter((a) => a.status === 'applied' || a.status === 'failed').slice(0, 6),
    [apps],
  );

  const counts = {
    queued: apps.filter((a) => a.status === 'queued').length,
    review: apps.filter((a) => a.status === 'pending_review').length,
    applying: apps.filter((a) => a.status === 'applying').length,
    applied: apps.filter((a) => a.status === 'applied').length,
    failed: apps.filter((a) => a.status === 'failed').length,
  };

  const awaiting = apps.filter((a) => a.status === 'pending_review').map((a) => a.id);

  const approveAll = () => {
    if (!awaiting.length) return;
    bulkApprove.mutate(awaiting, {
      onSuccess: (r) => notify(`${r.approved} applications approved and enqueued`, 'success'),
      onError: () => notify('Could not approve the staged applications', 'error'),
    });
  };

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1320 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 auto', minWidth: 240 }}>
          <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Run console</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
            {active.length
              ? `${active.length} application${active.length === 1 ? '' : 's'} in flight. Every step the agent takes is logged here.`
              : 'No application is currently in flight.'}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            title={connected ? 'Live updates connected' : 'Reconnecting…'}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 7, height: 36, padding: '0 12px',
              borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)',
              font: '600 11.5px/1 var(--font)', color: 'var(--text-3)',
            }}
          >
            <span
              style={{
                width: 7, height: 7, borderRadius: '50%',
                background: connected ? 'var(--applied)' : 'var(--review)',
                animation: connected ? 'aaPulse 1.8s var(--ease-io) infinite' : 'none',
              }}
            />
            {connected ? 'Live' : 'Reconnecting'}
          </span>
          {awaiting.length > 0 && (
            <button
              onClick={approveAll} disabled={bulkApprove.isPending}
              style={{ height: 36, padding: '0 15px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}
            >
              Approve {awaiting.length} staged
            </button>
          )}
        </div>
      </div>

      {intervention && (
        <div
          style={{
            ...card, display: 'flex', alignItems: 'center', gap: 12, padding: '13px 16px',
            marginBottom: 14, borderColor: 'var(--review-line)', background: 'var(--review-soft)',
          }}
        >
          <span style={{ color: 'var(--review)', display: 'grid', placeItems: 'center' }}><Icon name="alert" size={17} /></span>
          <span style={{ flex: '1 1 auto', font: '600 12.5px/1.4 var(--font)', color: 'var(--text)' }}>
            An application needs your input (CAPTCHA or 2FA) before it can continue.
          </span>
          <button
            onClick={() => navigate(`/applications/${intervention.application_id}`)}
            style={{ height: 30, padding: '0 13px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border-2)', color: 'var(--text)', font: '700 11.5px/1 var(--font)', cursor: 'pointer' }}
          >
            Resolve
          </button>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginBottom: 16 }}>
        <Stat label="QUEUED" value={counts.queued} color="var(--text-2)" />
        <Stat label="NEEDS REVIEW" value={counts.review} color="var(--review)" />
        <Stat label="IN FLIGHT" value={counts.applying} color="var(--accent)" />
        <Stat label="SUBMITTED" value={counts.applied} color="var(--offer)" />
        <Stat label="FAILED" value={counts.failed} color="var(--rejected)" />
      </div>

      {isLoading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} style={{ ...card, height: 116, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
          ))}
        </div>
      ) : active.length === 0 ? (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '60px 20px', textAlign: 'center' }}>
          <div style={{ display: 'grid', placeItems: 'center', width: 44, height: 44, borderRadius: 12, background: 'var(--accent-soft)', color: 'var(--accent)' }}>
            <Icon name="play" size={20} />
          </div>
          <div style={{ font: '700 14px/1.2 var(--font)', color: 'var(--text)' }}>No run in progress</div>
          <div style={{ font: '500 12.5px/1.4 var(--font)', color: 'var(--text-3)', maxWidth: 380 }}>
            Select roles on the Jobs screen and start a run. Every step the agent takes appears here.
          </div>
          <button
            onClick={() => navigate('/jobs')}
            style={{ marginTop: 6, height: 34, padding: '0 16px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}
          >
            Go to Jobs
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {active.map((a) => (
            <RunRow
              key={a.id} app={a}
              onOpen={() => navigate(`/applications/${a.id}`)}
              onApprove={() => approve.mutate(a.id, {
                onSuccess: () => notify(`Approved · ${a.job_title ?? 'application'}`, 'success'),
                onError: () => notify('Could not approve this application', 'error'),
              })}
              approving={approve.isPending}
            />
          ))}
        </div>
      )}

      {recentlyDone.length > 0 && (
        <>
          <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.14em', color: 'var(--text-4)', margin: '24px 0 11px' }}>
            RECENTLY FINISHED
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {recentlyDone.map((a) => (
              <RunRow key={a.id} app={a} onOpen={() => navigate(`/applications/${a.id}`)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ ...card, padding: '14px 15px' }}>
      <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.14em', color: 'var(--text-4)' }}>{label}</div>
      <div style={{ font: '800 24px/1 var(--font)', letterSpacing: '-.03em', color, marginTop: 9 }}>{value}</div>
    </div>
  );
}

function RunRow({ app, onOpen, onApprove, approving }: {
  app: Application; onOpen: () => void; onApprove?: () => void; approving?: boolean;
}) {
  const meta = statusMeta(app.status);
  const steps = buildAppTimeline(app.apply_mode, app.status);
  const pct = atsPercent(app.ats_score);
  const borderColor =
    app.status === 'failed' ? 'var(--failed-soft)'
      : app.status === 'pending_review' ? 'var(--review-line)'
        : 'var(--border)';

  return (
    <div style={{ ...card, padding: '14px 16px', borderColor }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <CompanyLogo name={app.company ?? '—'} size={34} radius={9} />
        <button
          onClick={onOpen}
          style={{ flex: '1 1 220px', minWidth: 0, background: 'none', border: 0, padding: 0, textAlign: 'left', cursor: 'pointer' }}
        >
          <div style={{ font: '700 13.5px/1.25 var(--font)', color: 'var(--text)' }}>{app.job_title ?? 'Untitled role'}</div>
          <div style={{ font: '500 11.5px/1.3 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>
            {app.company ?? '—'} · {app.apply_mode} mode · updated {relativeTime(app.updated_at)}
          </div>
        </button>
        {app.ats_score != null && (
          <span style={{ font: '700 12px/1 var(--mono)', color: atsColor(pct) }}>{pct}%</span>
        )}
        <span
          style={{
            display: 'inline-flex', alignItems: 'center', height: 24, padding: '0 10px',
            borderRadius: 999, font: '700 11px/1 var(--font)', color: meta.color, background: meta.soft,
          }}
        >
          {meta.label}
        </span>
        {onApprove && app.status === 'pending_review' && (
          <button
            onClick={onApprove} disabled={approving}
            style={{ height: 28, padding: '0 12px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 11.5px/1 var(--font)', cursor: 'pointer' }}
          >
            Approve
          </button>
        )}
      </div>

      <div style={{ display: 'flex', gap: 6, marginTop: 13, flexWrap: 'wrap' }}>
        {steps.map((s) => {
          const lit = s.state !== 'upcoming';
          return (
            <span
              key={s.key}
              title={s.diag ?? s.desc}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, height: 24, padding: '0 9px',
                borderRadius: 999, font: '600 11px/1 var(--font)',
                color: lit ? 'var(--text-2)' : 'var(--text-4)',
                background: s.state === 'current' || s.state === 'failed' ? 'var(--surface-2)' : 'transparent',
                border: `1px solid ${s.state === 'current' || s.state === 'failed' ? 'var(--border-2)' : 'var(--border)'}`,
              }}
            >
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: STEP_COLOR[s.state] }} />
              {s.label}
            </span>
          );
        })}
      </div>

      {steps.some((s) => s.diag) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginTop: 12, padding: '10px 12px', borderRadius: 'var(--r-md)', background: 'var(--failed-soft)' }}>
          <span style={{ font: '600 11.5px/1.4 var(--font)', color: 'var(--failed)' }}>
            {steps.find((s) => s.diag)?.diag}
          </span>
        </div>
      )}
    </div>
  );
}
