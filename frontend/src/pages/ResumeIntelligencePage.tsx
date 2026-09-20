import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import BranchDetail from '@/components/resumeIntelligence/BranchDetail';
import MasterResumeView from '@/components/resumeIntelligence/MasterResumeView';
import {
  useBranches, useCreateBranch, useResumeIntelligenceOverview,
} from '@/hooks/useResumeIntelligence';
import { useAppStore } from '@/store/useAppStore';
import { relativeTime } from '@/lib/status';
import type { RoleFamily } from '@/types/resumeIntelligence';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

const ROLE_FAMILY_LABEL: Record<RoleFamily, string> = {
  product: 'Product management', engineering: 'ML / AI engineering',
  architecture: 'Architecture & consulting', data: 'Data science & analytics',
};

/**
 * Resume Intelligence — the layer between the job market (via CVil-War's own job discovery)
 * and the résumé that actually gets sent. One factual master résumé, role-specific branches
 * derived from it, and full git-style version history with an explainable change log.
 *
 * One coherent page with internal view-state (overview / master / one branch), not a
 * multi-page enterprise system — matches this product's existing single-page-with-tabs
 * pattern (see ApplicationsPage).
 */
export default function ResumeIntelligencePage() {
  const notify = useAppStore((s) => s.showNotification);
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: overview, isLoading: overviewLoading } = useResumeIntelligenceOverview();
  const { data: branches, isLoading: branchesLoading } = useBranches();
  const createBranch = useCreateBranch();
  const [creating, setCreating] = useState(false);
  const [newRoleName, setNewRoleName] = useState('');
  const [newRoleFamily, setNewRoleFamily] = useState<RoleFamily>('product');

  const view = searchParams.get('view'); // null | "master" | branchId
  const tailorJobId = searchParams.get('tailorJobId'); // set by JobDrawer's "Tailor résumé"

  // Arriving from Jobs with a job to tailor but no branch chosen yet: land on the branch
  // grid with a clear prompt, rather than silently doing nothing with the query param.
  useEffect(() => {
    if (tailorJobId && !view) {
      notify('Choose a role to tailor this job against', 'info');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tailorJobId]);

  const openBranch = (branchId: string) => setSearchParams({ view: branchId, ...(tailorJobId ? { tailorJobId } : {}) });
  const openMaster = () => setSearchParams({ view: 'master' });
  const backToOverview = () => setSearchParams({});

  const submitCreate = () => {
    if (!newRoleName.trim()) return;
    createBranch.mutate(
      { role_name: newRoleName.trim(), role_family: newRoleFamily },
      {
        onSuccess: (branch) => {
          notify(`${branch.role_name} branch created from your master résumé`, 'success');
          setCreating(false);
          setNewRoleName('');
          openBranch(branch.id);
        },
        onError: () => notify('Could not create that role branch', 'error'),
      },
    );
  };

  if (view === 'master') {
    return <MasterResumeView onBack={backToOverview} />;
  }
  if (view) {
    return <BranchDetail branchId={view} onBack={backToOverview} tailorJobId={tailorJobId ?? undefined} />;
  }

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1180 }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Resume Intelligence</h1>
        <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
          One factual master résumé. Role-specific versions derived from it, tailored against real market signals — every change explained.
        </p>
      </div>

      {tailorJobId && (
        <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 12, padding: '13px 16px', marginBottom: 16, borderColor: 'var(--accent-line)', background: 'var(--accent-soft)' }}>
          <span style={{ color: 'var(--accent)', display: 'grid', placeItems: 'center' }}><Icon name="wand" size={17} /></span>
          <span style={{ flex: '1 1 auto', font: '600 12.5px/1.4 var(--font)', color: 'var(--text)' }}>
            Choose a role below to tailor your résumé for this job.
          </span>
        </div>
      )}

      {/* Summary strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginBottom: 16 }}>
        <StatCard label="Master résumé" value={overviewLoading ? '—' : (overview?.master_version?.version_label ?? '—')} />
        <StatCard label="Role profiles" value={overviewLoading ? '—' : String(overview?.branches.length ?? 0)} />
        <StatCard label="Recent changes" value={overviewLoading ? '—' : String(overview?.recent_changes_count ?? 0)} sub="last 30 days" />
      </div>

      {/* Master résumé card */}
      <section style={{ ...card, padding: 18, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <span style={{ display: 'grid', placeItems: 'center', width: 40, height: 40, borderRadius: 11, background: 'var(--accent-soft)', color: 'var(--accent)' }}>
          <Icon name="file" size={18} />
        </span>
        <div style={{ flex: '1 1 auto', minWidth: 200 }}>
          <div style={{ font: '700 14px/1.2 var(--font)' }}>Master résumé</div>
          <div style={{ font: '500 12px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>
            {overview?.master_version
              ? `${overview.master_version.version_label} · updated ${relativeTime(overview.master_version.created_at)}`
              : 'Loading…'}
            {' '}— the canonical, factual source every role branch derives from.
          </div>
        </div>
        <button onClick={openMaster} style={primaryBtn}>View master résumé</button>
      </section>

      {/* Role profiles */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ font: '700 14px/1 var(--font)' }}>Role profiles</div>
        <button onClick={() => setCreating((c) => !c)} style={ghostBtn}>
          <Icon name="plus" size={13} sw={2.2} /> New role
        </button>
      </div>

      {creating && (
        <div style={{ ...card, padding: 16, marginBottom: 14, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: '1 1 220px' }}>
            <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Role name</span>
            <input
              value={newRoleName} onChange={(e) => setNewRoleName(e.target.value)}
              placeholder="e.g. AI Product Manager"
              style={inputStyle}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Family</span>
            <select value={newRoleFamily} onChange={(e) => setNewRoleFamily(e.target.value as RoleFamily)} style={inputStyle}>
              {Object.entries(ROLE_FAMILY_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <button onClick={submitCreate} disabled={!newRoleName.trim() || createBranch.isPending} style={primaryBtn}>
            {createBranch.isPending ? 'Creating…' : 'Create branch'}
          </button>
        </div>
      )}

      {branchesLoading ? (
        <div style={{ ...card, height: 100, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
      ) : !branches || branches.length === 0 ? (
        <div style={{ ...card, padding: '40px 20px', textAlign: 'center', color: 'var(--text-3)' }}>
          <div style={{ font: '700 14px/1.3 var(--font)', color: 'var(--text)', marginBottom: 6 }}>No role profiles yet</div>
          <p style={{ margin: 0, font: '500 12.5px/1.5 var(--font)' }}>
            Create one for each role family you target — AI Product Manager, Data Scientist, MLOps Engineer — each starts as a copy of your master résumé.
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))', gap: 12 }}>
          {branches.map((b) => (
            <button
              key={b.id} onClick={() => openBranch(b.id)}
              style={{ ...card, padding: 16, textAlign: 'left', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 8 }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ font: '700 13.5px/1.25 var(--font)', color: 'var(--text)' }}>{b.role_name}</span>
                <span style={{ font: '600 10px/1 var(--mono)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.04em' }}>
                  {ROLE_FAMILY_LABEL[b.role_family]}
                </span>
              </div>
              <div style={{ font: '600 11.5px/1.4 var(--font)', color: 'var(--text-3)' }}>
                {b.current_version?.version_label ?? 'No version yet'}
                {b.current_version && ` · updated ${relativeTime(b.current_version.created_at)}`}
              </div>
              {tailorJobId && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, font: '700 11px/1 var(--font)', color: 'var(--accent)' }}>
                  <Icon name="wand" size={12} /> Tailor this job against {b.role_name}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ ...card, padding: '14px 16px' }}>
      <div style={{ font: '600 10.5px/1 var(--mono)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
      <div style={{ font: '800 20px/1.3 var(--font)', color: 'var(--text)', marginTop: 4 }}>{value}</div>
      {sub && <div style={{ font: '500 10.5px/1 var(--font)', color: 'var(--text-4)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  height: 34, padding: '0 16px', borderRadius: 'var(--r-md)', background: 'var(--accent)',
  border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer',
};
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px',
  borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)',
  color: 'var(--text-2)', font: '700 11.5px/1 var(--font)', cursor: 'pointer',
};
const inputStyle: React.CSSProperties = {
  height: 34, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
  border: '1px solid var(--border)', color: 'var(--text)', font: '600 12px/1 var(--font)', minWidth: 160,
};
