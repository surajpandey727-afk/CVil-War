import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import CompanyLogo from '@/components/ui/CompanyLogo';
import Icon from '@/components/ui/Icon';
import {
  useApplications, useApproveApplication, useBulkApprove, useUpdateApplicationStatus,
} from '@/hooks/useApplications';
import { useApplicationEvents } from '@/hooks/useApplicationEvents';
import { useResumes } from '@/hooks/useResumes';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useAppStore } from '@/store/useAppStore';
import { statusMeta, atsColor, atsPercent, isApprovable, relativeTime } from '@/lib/status';
import { buildAppTimeline, type TimelineState } from '@/lib/timeline';
import type { Application } from '@/types/application';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

/** The three top-level views. Every ApplicationStatus value belongs to exactly one, so this
 *  replaces the three previously separate pages (RunConsole, Applications, Dashboard's own
 *  pipeline table) rather than adding a fourth way of slicing the same data. */
type MainTab = 'active' | 'needs_action' | 'history';

const ACTIVE_STATUSES = new Set(['queued', 'approved', 'applying']);
const NEEDS_ACTION_STATUSES = new Set(['pending_review']);
const HISTORY_STATUSES = new Set(['applied', 'interview', 'offer', 'rejected', 'withdrawn', 'failed']);

const MAIN_TABS: { key: MainTab; label: string }[] = [
  { key: 'active', label: 'Active' },
  { key: 'needs_action', label: 'Needs action' },
  { key: 'history', label: 'History' },
];

const HISTORY_SUB_TABS: { key: string; label: string; status?: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'applied', label: 'Applied', status: 'applied' },
  { key: 'interview', label: 'Interview', status: 'interview' },
  { key: 'offer', label: 'Offer', status: 'offer' },
  { key: 'rejected', label: 'Rejected', status: 'rejected' },
  { key: 'withdrawn', label: 'Withdrawn', status: 'withdrawn' },
  { key: 'failed', label: 'Failed', status: 'failed' },
];

const STEP_COLOR: Record<TimelineState, string> = {
  done: 'var(--offer)', current: 'var(--accent)', upcoming: 'var(--text-4)',
  failed: 'var(--failed)', rejected: 'var(--rejected)', withdrawn: 'var(--withdrawn)',
};

/**
 * The one application surface — replaces RunConsolePage, the old status-tab-only
 * ApplicationsPage, and DashboardPage's separate pipeline table.
 *
 * Every ApplicationStatus maps to exactly one of the three top-level tabs: Active (still
 * moving), Needs action (waiting on the operator), History (settled, whatever the outcome).
 * That is the fix for the fragmentation this replaces — three pages independently deciding
 * what "in progress" meant, each with its own data-fetching and WebSocket wiring, could and
 * did disagree.
 */
export default function ApplicationsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const notify = useAppStore((s) => s.showNotification);
  const intervention = useAppStore((s) => s.pendingIntervention);

  const { lastMessage, connected } = useWebSocket();
  useApplicationEvents(lastMessage);

  const tabParam = searchParams.get('tab');
  const tab: MainTab = tabParam === 'needs_action' || tabParam === 'history' ? tabParam : 'active';
  const setTab = (next: MainTab) => setSearchParams(next === 'active' ? {} : { tab: next });

  // Synced to the URL (not local state) so a dashboard KPI can deep-link straight to, say,
  // "History > Interview" — a local-only sub-tab always reset to "all" on navigation, which
  // is why clicking "Interviews" anywhere else in the app landed on a tab that didn't show
  // any interviews.
  const subParam = searchParams.get('sub');
  const historySubTab = HISTORY_SUB_TABS.some((t) => t.key === subParam) ? subParam! : 'all';
  const setHistorySubTab = (next: string) =>
    setSearchParams(next === 'all' ? { tab: 'history' } : { tab: 'history', sub: next });
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // One fetch, filtered client-side into the three buckets — the same approach the console
  // this replaces already used for active/recently-finished, just applied consistently
  // across all three views instead of duplicated per page.
  const { data, isLoading, isError } = useApplications(1, 100);
  const approve = useApproveApplication();
  const bulkApprove = useBulkApprove();
  const updateStatus = useUpdateApplicationStatus();
  const { data: resumeData } = useResumes();
  const resumes = resumeData?.items ?? [];
  const [bulkResumeId, setBulkResumeId] = useState('');
  const [autoApplying, setAutoApplying] = useState(false);

  const apps = useMemo(() => data?.items ?? [], [data]);
  const active = useMemo(() => apps.filter((a) => ACTIVE_STATUSES.has(a.status)), [apps]);
  const needsAction = useMemo(() => apps.filter((a) => NEEDS_ACTION_STATUSES.has(a.status)), [apps]);
  const history = useMemo(() => {
    const settled = apps.filter((a) => HISTORY_STATUSES.has(a.status));
    const subStatus = HISTORY_SUB_TABS.find((t) => t.key === historySubTab)?.status;
    return subStatus ? settled.filter((a) => a.status === subStatus) : settled;
  }, [apps, historySubTab]);

  const counts = {
    queued: apps.filter((a) => a.status === 'queued').length,
    applying: apps.filter((a) => a.status === 'applying').length,
    review: needsAction.length,
  };

  const approveAll = () => {
    const ids = needsAction.map((a) => a.id);
    if (!ids.length) return;
    bulkApprove.mutate(ids, {
      onSuccess: (r) => notify(`${r.approved} approved · queued for the agent`, 'success'),
      onError: () => notify('Could not approve the staged applications', 'error'),
    });
  };

  // One résumé, attached to every needs-action app that doesn't already have one, then the
  // whole batch approved together — the point is skipping the "open each app, pick a résumé,
  // approve" loop for a run where every role gets the same CV.
  const autoApplyAll = async () => {
    if (!bulkResumeId || !needsAction.length) return;
    setAutoApplying(true);
    const toAttach = needsAction.filter((a) => !a.resume_id);
    try {
      const results = await Promise.allSettled(
        toAttach.map((a) =>
          updateStatus.mutateAsync({ appId: a.id, update: { status: a.status, resume_id: bulkResumeId } }),
        ),
      );
      const attachFailures = results.filter((r) => r.status === 'rejected').length;
      const approveResult = await bulkApprove.mutateAsync(needsAction.map((a) => a.id));
      if (attachFailures > 0) {
        notify(
          `${approveResult.approved} approved · ${attachFailures} résumé attachment(s) failed`,
          'warning',
        );
      } else {
        notify(`Résumé attached and ${approveResult.approved} approved · queued for the agent`, 'success');
      }
    } catch {
      notify('Auto-apply could not complete — some applications may be unchanged', 'error');
    } finally {
      setAutoApplying(false);
    }
  };

  const approveSelected = () => {
    const ids = [...selected];
    if (!ids.length) return;
    bulkApprove.mutate(ids, {
      onSuccess: (r) => { notify(`${r.approved} approved · queued for the agent`, 'success'); setSelected(new Set()); },
      onError: () => notify('Bulk approve failed', 'error'),
    });
  };

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1320 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 auto', minWidth: 240 }}>
          <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Applications</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
            Your live pipeline — what&apos;s moving, what needs you, and what&apos;s settled.
          </p>
        </div>
        <span
          title={connected ? 'Live updates connected' : 'Reconnecting…'}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 7, height: 34, padding: '0 12px',
            borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)',
            font: '600 11.5px/1 var(--font)', color: 'var(--text-3)',
          }}
        >
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: connected ? 'var(--applied)' : 'var(--review)', animation: connected ? 'aaPulse 1.8s var(--ease-io) infinite' : 'none' }} />
          {connected ? 'Live' : 'Reconnecting'}
        </span>
      </div>

      {intervention && (
        <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 12, padding: '13px 16px', marginBottom: 14, borderColor: 'var(--review-line)', background: 'var(--review-soft)' }}>
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

      <div role="tablist" aria-label="Applications view" style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {MAIN_TABS.map((t) => {
          const activeTab = t.key === tab;
          const badge = t.key === 'active' ? counts.queued + counts.applying : t.key === 'needs_action' ? counts.review : 0;
          return (
            <button
              key={t.key}
              role="tab"
              aria-selected={activeTab}
              onClick={() => { setTab(t.key); setSelected(new Set()); }}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7, height: 34, padding: '0 14px',
                borderRadius: 'var(--r-md)', border: `1px solid ${activeTab ? 'var(--accent-line)' : 'var(--border)'}`,
                background: activeTab ? 'var(--accent-soft)' : 'var(--surface-2)',
                color: activeTab ? 'var(--accent)' : 'var(--text-3)', font: '700 12.5px/1 var(--font)', cursor: 'pointer',
              }}
            >
              {t.label}
              {badge > 0 && (
                <span style={{ display: 'inline-grid', placeItems: 'center', minWidth: 18, height: 18, padding: '0 5px', borderRadius: 999, background: activeTab ? 'var(--accent)' : 'var(--surface-3)', color: activeTab ? 'var(--accent-ink)' : 'var(--text-3)', font: '700 10.5px/1 var(--mono)' }}>
                  {badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {tab === 'active' && (
        <ActiveOrNeedsActionView
          items={active} isLoading={isLoading} isError={isError} navigate={navigate}
          emptyTitle="No run in progress"
          emptyBody="Select roles on the Jobs screen and start a run. Every step the agent takes appears here."
          approve={undefined}
        />
      )}

      {tab === 'needs_action' && (
        <>
          {needsAction.length > 0 && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
              <select
                aria-label="Résumé for auto-apply"
                value={bulkResumeId}
                onChange={(e) => setBulkResumeId(e.target.value)}
                style={{ height: 34, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)', font: '600 12px/1 var(--font)', minWidth: 180 }}
              >
                <option value="">Auto-apply with résumé…</option>
                {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
              <button
                onClick={() => void autoApplyAll()}
                disabled={!bulkResumeId || autoApplying}
                title="Attach this résumé to every needs-action application that doesn't have one, then approve all"
                style={{ height: 34, padding: '0 14px', borderRadius: 'var(--r-md)', background: bulkResumeId ? 'var(--surface-2)' : 'var(--surface-3)', border: '1px solid var(--border-2)', color: bulkResumeId ? 'var(--text)' : 'var(--text-4)', font: '700 12.5px/1 var(--font)', cursor: bulkResumeId ? 'pointer' : 'default' }}
              >
                {autoApplying ? 'Applying…' : `Auto-apply all ${needsAction.length}`}
              </button>
              <button
                onClick={approveAll} disabled={bulkApprove.isPending}
                style={{ height: 34, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}
              >
                Approve all {needsAction.length}
              </button>
            </div>
          )}
          <ActiveOrNeedsActionView
            items={needsAction} isLoading={isLoading} isError={isError} navigate={navigate}
            emptyTitle="Nothing needs you right now"
            emptyBody="Applications staged for review, or paused for a decision, show up here."
            approve={(a) => approve.mutate(a.id, {
              onSuccess: () => notify(`Approved · ${a.job_title ?? 'application'}`, 'success'),
              onError: () => notify('Could not approve this application', 'error'),
            })}
            approving={approve.isPending}
          />
        </>
      )}

      {tab === 'history' && (
        <>
          <div role="tablist" aria-label="Filter history" style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
            {HISTORY_SUB_TABS.map((t) => {
              const activeSub = t.key === historySubTab;
              return (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={activeSub}
                  onClick={() => { setHistorySubTab(t.key); setSelected(new Set()); }}
                  style={{ height: 30, padding: '0 11px', borderRadius: 'var(--r-md)', border: `1px solid ${activeSub ? 'var(--accent-line)' : 'var(--border)'}`, background: activeSub ? 'var(--accent-soft)' : 'var(--surface-2)', color: activeSub ? 'var(--accent)' : 'var(--text-3)', font: '600 11.5px/1 var(--font)', cursor: 'pointer' }}
                >
                  {t.label}
                </button>
              );
            })}
          </div>

          {selected.size > 0 && (
            <div style={{ ...card, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '11px 16px', marginBottom: 12, borderColor: 'var(--accent-line)', background: 'var(--accent-soft)' }}>
              <span style={{ font: '700 12.5px/1 var(--font)', color: 'var(--accent)' }}>{selected.size} selected</span>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => setSelected(new Set())} style={{ height: 32, padding: '0 12px', borderRadius: 'var(--r-md)', background: 'transparent', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '600 12px/1 var(--font)', cursor: 'pointer' }}>Clear</button>
                <button onClick={approveSelected} disabled={bulkApprove.isPending} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 32, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12px/1 var(--font)', cursor: 'pointer' }}>
                  <Icon name="check" size={13} sw={2.2} /> Approve {selected.size}
                </button>
              </div>
            </div>
          )}

          <div style={{ ...card, overflow: 'hidden' }}>
            {isError ? (
              <Notice text="Couldn't load applications. Retry in a moment." />
            ) : isLoading ? (
              <div style={{ padding: 8 }}>
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} style={{ height: 'var(--row-h)', margin: 4, borderRadius: 'var(--r-sm)', background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
                ))}
              </div>
            ) : history.length === 0 ? (
              <div style={{ padding: '46px 20px', textAlign: 'center', color: 'var(--text-3)' }}>
                <div style={{ display: 'inline-grid', placeItems: 'center', width: 44, height: 44, borderRadius: 12, background: 'var(--surface-2)', color: 'var(--text-4)', marginBottom: 12 }}><Icon name="inbox" size={20} /></div>
                <div style={{ font: '700 14px/1.2 var(--font)', color: 'var(--text)' }}>Nothing here yet</div>
                <p style={{ margin: '6px 0 0', font: '500 12px/1.4 var(--font)' }}>No applications match this filter.</p>
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 680 }}>
                  <thead>
                    <tr>
                      <th style={thStyle(false)} />
                      {['Role', 'Mode', 'Status', 'ATS', 'Applied', ''].map((h, i) => (
                        <th key={i} style={thStyle(i === 3)}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((a) => (
                      <Row key={a.id} app={a} selected={selected.has(a.id)} onToggle={() => toggle(a.id)} onOpen={() => navigate(`/applications/${a.id}`)} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function ActiveOrNeedsActionView({
  items, isLoading, isError, navigate, emptyTitle, emptyBody, approve, approving,
}: {
  items: Application[];
  isLoading: boolean;
  isError: boolean;
  navigate: (path: string) => void;
  emptyTitle: string;
  emptyBody: string;
  approve?: (a: Application) => void;
  approving?: boolean;
}) {
  if (isError) return <div style={card}><Notice text="Couldn't load applications. Retry in a moment." /></div>;

  if (isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} style={{ ...card, height: 116, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div style={{ ...card, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '60px 20px', textAlign: 'center' }}>
        <div style={{ display: 'grid', placeItems: 'center', width: 44, height: 44, borderRadius: 12, background: 'var(--accent-soft)', color: 'var(--accent)' }}>
          <Icon name="play" size={20} />
        </div>
        <div style={{ font: '700 14px/1.2 var(--font)', color: 'var(--text)' }}>{emptyTitle}</div>
        <div style={{ font: '500 12.5px/1.4 var(--font)', color: 'var(--text-3)', maxWidth: 380 }}>{emptyBody}</div>
        <button
          onClick={() => navigate('/jobs')}
          style={{ marginTop: 6, height: 34, padding: '0 16px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}
        >
          Go to Jobs
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {items.map((a) => (
        <RunRow
          key={a.id} app={a}
          onOpen={() => navigate(`/applications/${a.id}`)}
          onApprove={approve ? () => approve(a) : undefined}
          approving={approving}
        />
      ))}
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
        {app.resume_id ? (
          <span
            title={app.resume_archived ? 'This résumé has since been archived' : undefined}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5, height: 24, padding: '0 9px',
              borderRadius: 999, font: '600 11px/1 var(--font)',
              color: app.resume_archived ? 'var(--review)' : 'var(--text-3)',
              background: app.resume_archived ? 'var(--review-soft)' : 'var(--surface-2)',
              maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
          >
            <Icon name="file" size={11} /> {app.resume_name ?? 'Résumé'}
          </span>
        ) : (
          <span
            title="No résumé attached — this application cannot be scored or reliably submitted"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5, height: 24, padding: '0 9px',
              borderRadius: 999, font: '700 11px/1 var(--font)', color: 'var(--rejected)', background: 'var(--rejected-soft)',
            }}
          >
            <Icon name="alert" size={11} /> No résumé
          </span>
        )}
        <span style={{ display: 'inline-flex', alignItems: 'center', height: 24, padding: '0 10px', borderRadius: 999, font: '700 11px/1 var(--font)', color: meta.color, background: meta.soft }}>
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

function thStyle(center: boolean): React.CSSProperties {
  return { textAlign: center ? 'center' : 'left', font: '600 10.5px/1 var(--mono)', letterSpacing: '.08em', color: 'var(--text-4)', textTransform: 'uppercase', padding: '11px 16px', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
}

function Row({ app, selected, onToggle, onOpen }: { app: Application; selected: boolean; onToggle: () => void; onOpen: () => void }) {
  const sm = statusMeta(app.status);
  const approvable = isApprovable(app.status);
  return (
    <tr onClick={onOpen} style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
      <td style={{ padding: '0 8px 0 16px', width: 34 }} onClick={(e) => e.stopPropagation()}>
        {approvable && (
          <input
            type="checkbox"
            aria-label={`Select ${app.job_title ?? 'application'}`}
            checked={selected}
            onChange={onToggle}
            style={{ width: 15, height: 15, accentColor: 'var(--accent)', cursor: 'pointer' }}
          />
        )}
      </td>
      <td style={{ padding: '0 16px', height: 'var(--row-h)' }}>
        <div style={{ font: '700 12.5px/1.25 var(--font)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 260 }}>{app.job_title ?? 'Untitled role'}</div>
        <div style={{ font: '500 11px/1.3 var(--font)', color: 'var(--text-3)', marginTop: 2 }}>{app.company ?? '—'}</div>
      </td>
      <td style={{ padding: '0 16px' }}>
        <span style={{ font: '600 10.5px/1 var(--mono)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.03em' }}>{app.apply_mode}</span>
      </td>
      <td style={{ padding: '0 16px' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 22, padding: '0 9px', borderRadius: 999, background: sm.soft, color: sm.color, font: '700 11px/1 var(--font)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: sm.color }} /> {sm.label}
        </span>
      </td>
      <td style={{ padding: '0 16px', textAlign: 'center' }}>
        <span style={{ font: '700 12.5px/1 var(--mono)', color: app.ats_score != null ? atsColor(atsPercent(app.ats_score)) : 'var(--text-4)' }}>{app.ats_score != null ? atsPercent(app.ats_score) : '—'}</span>
      </td>
      <td style={{ padding: '0 16px' }}>
        <span style={{ font: '500 11.5px/1 var(--mono)', color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{relativeTime(app.applied_at ?? app.created_at)}</span>
      </td>
      <td style={{ padding: '0 16px', textAlign: 'right', color: 'var(--text-4)' }}><Icon name="chevR" size={15} /></td>
    </tr>
  );
}

function Notice({ text }: { text: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '30px 20px', justifyContent: 'center', color: 'var(--text-3)', font: '500 12.5px/1.4 var(--font)' }}>
      <span style={{ color: 'var(--failed)' }}><Icon name="alert" size={16} /></span> {text}
    </div>
  );
}
