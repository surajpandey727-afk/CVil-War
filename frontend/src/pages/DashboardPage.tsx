import { useNavigate } from 'react-router-dom';

import ActionQueue from '@/components/dashboard/ActionQueue';
import Icon, { type IconName } from '@/components/ui/Icon';
import { useDashboardStats } from '@/hooks/useAnalytics';
import { useApplications } from '@/hooks/useApplications';
import { useAuthStore } from '@/store/useAuthStore';
import { atsColor, atsPercent } from '@/lib/status';
import type { Application } from '@/types/application';

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

function firstName(name?: string | null, email?: string): string {
  if (name && name.trim()) return name.trim().split(/\s+/)[0] ?? name;
  return (email ?? 'there').split('@')[0] ?? 'there';
}

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

export default function DashboardPage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const { data: stats } = useDashboardStats();
  const { data: apps, isLoading, isError } = useApplications(1, 20);

  const items = apps?.items ?? [];
  const live = items.find((a) => a.status === 'applying');

  // Every card links straight to the filtered view backing its number — "History > Interview"
  // etc. — via ApplicationsPage's URL-synced tab/sub params, rather than to a generic page the
  // operator then has to re-filter by hand (or, previously, a tab that showed nothing at all
  // because the sub-filter was local-only state that reset on navigation).
  const kpis: { label: string; value: string; icon: IconName; color: string; to?: string }[] = [
    { label: 'Jobs found today', value: fmt(stats?.jobs_found_today), icon: 'search', color: 'var(--text-2)', to: '/jobs' },
    { label: 'Unique jobs', value: fmt(stats?.unique_jobs), icon: 'briefcase', color: 'var(--text-2)', to: '/jobs' },
    { label: 'Sponsor confirmed', value: fmt(stats?.sponsor_confirmed_jobs), icon: 'shield', color: 'var(--offer)', to: '/jobs' },
    { label: 'CVs generated', value: fmt(stats?.cvs_generated), icon: 'file', color: 'var(--text-2)', to: '/resumes' },
    { label: 'Applications', value: fmt(stats?.total_applications), icon: 'inbox', color: 'var(--text-2)', to: '/applications' },
    { label: 'Applied', value: fmt(stats?.applications_applied), icon: 'check', color: 'var(--applied)', to: '/applications?tab=history&sub=applied' },
    // Sent today and this week, counted on the submission timestamp rather than on rows
    // created — a queued application is not an application sent, and conflating them
    // flatters the number that matters most.
    { label: 'Sent today', value: fmt(stats?.submitted_today), icon: 'clock', color: 'var(--text-2)', to: '/applications?tab=history&sub=applied' },
    { label: 'Sent this week', value: fmt(stats?.submitted_this_week), icon: 'clock', color: 'var(--text-2)', to: '/applications?tab=history&sub=applied' },
    { label: 'Interviews', value: fmt(stats?.applications_interview), icon: 'activity', color: 'var(--interview)', to: '/applications?tab=history&sub=interview' },
    { label: 'Offers', value: fmt(stats?.applications_offer), icon: 'target', color: 'var(--offer)', to: '/applications?tab=history&sub=offer' },
    { label: 'Failed', value: fmt(stats?.applications_failed), icon: 'alert', color: 'var(--failed)', to: '/applications?tab=history&sub=failed' },
    { label: 'Avg ATS', value: stats ? String(atsPercent(stats.avg_ats_score)) : '—', icon: 'gauge', color: 'var(--accent)', to: '/analytics' },
    { label: 'LLM cost', value: stats ? `$${(stats.total_llm_cost_usd ?? 0).toFixed(2)}` : '—', icon: 'dollar', color: 'var(--accent)', to: '/analytics' },
  ];

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both' }}>
      {/* Greeting */}
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 22 }}>
        <div>
          <h1 style={{ margin: 0, font: '800 25px/1.1 var(--font)', letterSpacing: '-.03em' }}>
            {greeting()}, {firstName(user?.full_name, user?.email)}
          </h1>
          <p style={{ margin: '7px 0 0', font: '500 13.5px/1.4 var(--font)', color: 'var(--text-3)' }}>
            Your agent applied to <span style={{ color: 'var(--applied)', fontWeight: 700 }}>{fmt(stats?.applications_applied)} {stats?.applications_applied === 1 ? 'role' : 'roles'}</span> and flagged{' '}
            <span style={{ color: 'var(--review)', fontWeight: 700 }}>{fmt(stats?.applications_pending)}</span> for review.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <button
            onClick={() => navigate('/analytics')}
            style={{ display: 'flex', alignItems: 'center', gap: 7, height: 36, padding: '0 12px', borderRadius: 'var(--r-md)', background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text-2)', font: '600 12.5px/1 var(--font)', cursor: 'pointer' }}
          >
            <span style={{ display: 'grid', placeItems: 'center', color: 'var(--text-3)' }}><Icon name="clock" size={15} /></span>
            Last 30 days
          </button>
          <button
            onClick={() => navigate('/jobs')}
            style={{ display: 'flex', alignItems: 'center', gap: 7, height: 36, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer', boxShadow: '0 0 0 1px var(--accent-line),0 6px 16px -8px var(--accent-glow)' }}
          >
            <span style={{ display: 'grid', placeItems: 'center' }}><Icon name="search" size={15} sw={2} /></span>
            New search
          </button>
        </div>
      </div>

      {/* What needs the user, above everything else.
          The KPI strip below reports what has happened; this reports what to do about it,
          which is the only part that is time-sensitive — so it goes first. */}
      <div style={{ marginBottom: 18 }}>
        <ActionQueue limit={6} />
      </div>

      {/* Live now — an in-flight application (agent applying right now) */}
      {live && (
        <div
          onClick={() => navigate(`/applications/${live.id}`)}
          style={{ background: 'var(--surface)', border: '1px solid var(--accent-line)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1),inset 0 0 40px -30px var(--accent-glow)', padding: 16, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 14, cursor: 'pointer' }}
        >
          <span style={{ position: 'relative', width: 10, height: 10, flex: '0 0 auto' }}>
            <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: 'var(--accent)', animation: 'aaPulse 1.6s infinite' }} />
            <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: 'var(--accent)', animation: 'aaRing 1.6s infinite' }} />
          </span>
          <div style={{ flex: '1 1 auto', minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ font: '700 12px/1 var(--font)', color: 'var(--accent)' }}>Live now</span>
              <span style={{ font: '600 10.5px/1 var(--mono)', color: 'var(--text-4)' }}>agent applying</span>
            </div>
            <div style={{ font: '700 14px/1.3 var(--font)', marginTop: 5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{live.job_title ?? 'Untitled role'}</div>
            <div style={{ font: '500 12px/1.3 var(--font)', color: 'var(--text-3)', marginTop: 2 }}>{live.company ?? '—'}</div>
          </div>
          {live.ats_score != null && (
            <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <span style={{ font: '800 20px/1 var(--mono)', color: atsColor(atsPercent(live.ats_score)) }}>{atsPercent(live.ats_score)}</span>
              <span style={{ font: '600 8px/1 var(--mono)', letterSpacing: '.1em', color: 'var(--text-4)' }}>ATS</span>
            </div>
          )}
        </div>
      )}

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(178px,1fr))', gap: 14, marginBottom: 18 }}>
        {kpis.map((k, i) => (
          <button
            key={k.label}
            onClick={k.to ? () => navigate(k.to!) : undefined}
            style={{
              ...card, padding: '15px 15px 14px', overflow: 'hidden', animation: 'aaUp .5s var(--ease) both',
              animationDelay: `${i * 40}ms`, textAlign: 'left',
              cursor: k.to ? 'pointer' : 'default', font: 'inherit', color: 'inherit',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.06em' }}>{k.label}</span>
              <span style={{ display: 'grid', placeItems: 'center', color: k.color }}><Icon name={k.icon} size={16} /></span>
            </div>
            <div style={{ font: '800 27px/1 var(--font)', letterSpacing: '-.03em', color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>{k.value}</div>
          </button>
        ))}
      </div>

      {/* Pipeline summary — a read-only KPI, not a second interactive table. The row-level
          view (with approve actions) lives in one place now: /applications. */}
      <div style={{ ...card, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '15px 18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ font: '700 14px/1 var(--font)', letterSpacing: '-.01em' }}>Application pipeline</span>
            <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)' }}>{apps ? apps.total : ''}</span>
          </div>
          <button
            onClick={() => navigate('/applications')}
            style={{ display: 'flex', alignItems: 'center', gap: 6, height: 30, padding: '0 11px', borderRadius: 'var(--r-md)', background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-2)', font: '600 12px/1 var(--font)', cursor: 'pointer' }}
          >
            Open Applications <Icon name="chevR" size={13} />
          </button>
        </div>

        {isError ? (
          <Notice icon="alert" text="Couldn't load your pipeline. Retry in a moment." />
        ) : isLoading ? (
          <div style={{ padding: '0 18px 18px' }}>
            <div style={{ height: 60, borderRadius: 'var(--r-sm)', background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
          </div>
        ) : items.length === 0 ? (
          <div style={{ padding: '0 20px 40px', textAlign: 'center' }}>
            <div style={{ display: 'inline-grid', placeItems: 'center', width: 46, height: 46, borderRadius: 12, background: 'var(--accent-soft)', color: 'var(--accent)', marginBottom: 14 }}>
              <Icon name="inbox" size={22} />
            </div>
            <div style={{ font: '700 15px/1.2 var(--font)' }}>Your pipeline is empty</div>
            <p style={{ margin: '7px 0 16px', font: '500 12.5px/1.4 var(--font)', color: 'var(--text-3)' }}>Run a search and the agent will start building your pipeline.</p>
            <button
              onClick={() => navigate('/jobs')}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 34, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}
            >
              <Icon name="search" size={14} sw={2} /> Start a search
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 0, borderTop: '1px solid var(--border)' }}>
            {pipelineBreakdown(items).map((b) => (
              <button
                key={b.status}
                onClick={() => navigate(pipelineStatusLink(b.status))}
                style={{
                  display: 'flex', flexDirection: 'column', gap: 6, padding: '14px 18px',
                  background: 'transparent', border: 0, borderRight: '1px solid var(--border)',
                  textAlign: 'left', cursor: 'pointer',
                }}
              >
                <span style={{ font: '600 10.5px/1 var(--mono)', letterSpacing: '.06em', color: 'var(--text-4)', textTransform: 'uppercase' }}>{b.label}</span>
                <span style={{ font: '800 20px/1 var(--font)', color: b.color }}>{b.count}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Where each pipeline status actually lives on /applications — active statuses share the
 *  Active tab (no sub-filter there), pending_review has its own tab, and every settled status
 *  is a History sub-tab. Previously every non-review status linked to the same bare
 *  `/applications`, so "Interview" landed on the Active tab showing queued/applying rows
 *  instead of any interviews. */
function pipelineStatusLink(status: string): string {
  if (status === 'pending_review') return '/applications?tab=needs_action';
  if (status === 'queued' || status === 'applying') return '/applications';
  return `/applications?tab=history&sub=${status}`;
}

/** One glanceable count per status band — click-through to the real (interactive) view at
 *  /applications rather than duplicating its row rendering and approve actions here. */
function pipelineBreakdown(items: Application[]): { status: string; label: string; count: number; color: string }[] {
  const by = (status: string) => items.filter((a) => a.status === status).length;
  return [
    { status: 'queued', label: 'Queued', count: by('queued'), color: 'var(--text-2)' },
    { status: 'pending_review', label: 'Needs review', count: by('pending_review'), color: 'var(--review)' },
    { status: 'applying', label: 'In flight', count: by('applying'), color: 'var(--accent)' },
    { status: 'applied', label: 'Applied', count: by('applied'), color: 'var(--applied)' },
    { status: 'interview', label: 'Interview', count: by('interview'), color: 'var(--interview)' },
    { status: 'offer', label: 'Offer', count: by('offer'), color: 'var(--offer)' },
  ];
}

function fmt(n: number | undefined): string {
  return n == null ? '—' : String(n);
}

function Notice({ icon, text }: { icon: IconName; text: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '30px 20px', justifyContent: 'center', color: 'var(--text-3)', font: '500 12.5px/1.4 var(--font)' }}>
      <span style={{ color: 'var(--failed)' }}><Icon name={icon} size={16} /></span>
      {text}
    </div>
  );
}
