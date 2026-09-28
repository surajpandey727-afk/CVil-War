import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import ChangeLogTimeline from '@/components/resumeIntelligence/ChangeLogTimeline';
import DiffView from '@/components/resumeIntelligence/DiffView';
import ResumeContentView from '@/components/resumeIntelligence/ResumeContentView';
import TailorReview from '@/components/resumeIntelligence/TailorReview';
import {
  useBranch, useBranchVersions, useDeleteBranch, useMarketSignals,
} from '@/hooks/useResumeIntelligence';
import { useAppStore } from '@/store/useAppStore';
import { atsColor } from '@/lib/status';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

type Tab = 'resume' | 'market' | 'history' | 'tailor';

export default function BranchDetail({ branchId, onBack, tailorJobId }: {
  branchId: string; onBack: () => void; tailorJobId?: string;
}) {
  const notify = useAppStore((s) => s.showNotification);
  const { data: branch, isLoading } = useBranch(branchId);
  const { data: versions } = useBranchVersions(branchId);
  const marketSignals = useMarketSignals(branchId);
  const deleteBranch = useDeleteBranch();
  const [tab, setTab] = useState<Tab>(tailorJobId ? 'tailor' : 'resume');
  const [compare, setCompare] = useState<{ from: string; to: string } | null>(null);

  if (isLoading || !branch) {
    return <div style={{ ...card, height: 200, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />;
  }

  const mySkills = new Set(branch.current_content?.skills.map((s) => s.toLowerCase()) ?? []);
  const signalEntries = Object.entries(marketSignals.data?.signals ?? {}).sort((a, b) => b[1].frequency - a[1].frequency);
  const covered = signalEntries.filter(([skill]) => mySkills.has(skill.toLowerCase()));
  const gaps = signalEntries.filter(([skill]) => !mySkills.has(skill.toLowerCase()));

  const confirmDelete = () => {
    if (!window.confirm(`Delete the ${branch.role_name} branch and all its versions? This cannot be undone.`)) return;
    deleteBranch.mutate(branchId, {
      onSuccess: () => { notify(`${branch.role_name} branch deleted`, 'success'); onBack(); },
      onError: () => notify('Could not delete that branch', 'error'),
    });
  };

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1000 }}>
      <button onClick={onBack} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 30, padding: '0 10px 0 8px', marginBottom: 16, borderRadius: 'var(--r-md)', background: 'transparent', border: 0, color: 'var(--text-3)', font: '600 12.5px/1 var(--font)', cursor: 'pointer' }}>
        <Icon name="chevL" size={15} /> Resume Intelligence
      </button>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 4, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, font: '800 22px/1.2 var(--font)', letterSpacing: '-.02em' }}>{branch.role_name}</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
            {branch.description || 'Derived from your master résumé, positioned for this role.'}
          </p>
        </div>
        <button
          onClick={confirmDelete}
          title="Delete this role branch and every version under it. This cannot be undone."
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 11px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--rejected)', font: '600 11.5px/1 var(--font)', cursor: 'pointer' }}>
          <Icon name="trash" size={12} /> Delete branch
        </button>
      </div>

      <div role="tablist" style={{ display: 'flex', gap: 4, margin: '16px 0' }}>
        {([['resume', 'Résumé'], ['market', 'Market signals'], ['tailor', 'Tailor for a job'], ['history', 'Version history']] as const).map(([key, label]) => (
          <button
            key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
            style={{
              height: 32, padding: '0 13px', borderRadius: 'var(--r-md)',
              border: `1px solid ${tab === key ? 'var(--accent-line)' : 'var(--border)'}`,
              background: tab === key ? 'var(--accent-soft)' : 'var(--surface-2)',
              color: tab === key ? 'var(--accent)' : 'var(--text-3)', font: '700 12px/1 var(--font)', cursor: 'pointer',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'resume' && branch.current_content && (
        <ResumeContentView content={branch.current_content} editable={false} />
      )}

      {tab === 'market' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ ...card, padding: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
              {marketSignals.data
                ? `From ${marketSignals.data.matched_jobs} of your ${marketSignals.data.total_jobs_scanned} discovered jobs matching this role's title.`
                : 'Computing…'}
            </div>
            <button
              onClick={() => marketSignals.refresh.mutate(undefined, {
                onSuccess: () => notify('Market signals refreshed', 'success'),
                onError: () => notify('Could not refresh market signals', 'error'),
              })}
              disabled={marketSignals.refresh.isPending}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 11px', borderRadius: 999, background: 'var(--accent-soft)', border: '1px solid var(--accent-line)', color: 'var(--accent)', font: '700 11px/1 var(--font)', cursor: 'pointer' }}
            >
              <Icon name="refresh" size={11} /> {marketSignals.refresh.isPending ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>

          {signalEntries.length === 0 ? (
            <div style={{ ...card, padding: '30px 20px', textAlign: 'center', color: 'var(--text-3)' }}>
              <p style={{ margin: 0, font: '500 12.5px/1.5 var(--font)' }}>
                No discovered jobs match this role's title yet — market signals appear once CVil-War has found some.
              </p>
            </div>
          ) : (
            <>
              <SignalSection title="Your coverage" entries={covered} tone="var(--applied)" icon="check" />
              <SignalSection title="Gaps" entries={gaps} tone="var(--rejected)" icon="alert" />
            </>
          )}
        </div>
      )}

      {tab === 'tailor' && (
        <TailorReview branchId={branchId} initialJobId={tailorJobId} />
      )}

      {tab === 'history' && (
        compare ? (
          <>
            <button onClick={() => setCompare(null)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 10px', marginBottom: 10, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-3)', font: '600 11.5px/1 var(--font)', cursor: 'pointer' }}>
              <Icon name="chevL" size={12} /> Back to history
            </button>
            <DiffView fromId={compare.from} toId={compare.to} />
          </>
        ) : (
          <ChangeLogTimeline versions={versions ?? []} onCompare={(from, to) => setCompare({ from, to })} />
        )
      )}
    </div>
  );
}

function SignalSection({ title, entries, tone, icon }: {
  title: string; entries: [string, { frequency: number; matched_jobs: number; total_jobs: number }][];
  tone: string; icon: 'check' | 'alert';
}) {
  if (entries.length === 0) return null;
  return (
    <div style={{ ...card, padding: 16 }}>
      <div style={{ font: '700 10.5px/1 var(--font)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 10 }}>{title}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {entries.map(([skill, signal]) => {
          const pct = Math.round(signal.frequency * 100);
          return (
            <div key={skill} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ color: tone, display: 'grid', placeItems: 'center', flex: '0 0 auto' }}><Icon name={icon} size={13} /></span>
              <span style={{ flex: '0 0 160px', font: '700 12.5px/1.3 var(--font)', color: 'var(--text)' }}>{skill}</span>
              <div style={{ flex: '1 1 auto', height: 6, borderRadius: 3, background: 'var(--surface-3)', overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: atsColor(pct) }} />
              </div>
              <span style={{ flex: '0 0 auto', font: '700 11px/1 var(--mono)', color: 'var(--text-3)' }}>
                {pct}% · {signal.matched_jobs}/{signal.total_jobs}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
