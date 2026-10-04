import Icon from '@/components/ui/Icon';
import { atsPercent } from '@/lib/status';
import type { Resume } from '@/types/resume';
import type { TailorRowState } from '@/types/ats';

interface Props {
  selectedCount: number;
  totalCount: number;
  resumes: Resume[];
  baseResumeId: string;
  onBaseResumeChange: (id: string) => void;
  onTailor: () => void;
  onRegenerate: () => void;
  onCancel: () => void;
  onApprove: () => void;
  onApproveAll: () => void;
  onSelectAll: () => void;
  onClear: () => void;
  running: boolean;
  approving: boolean;
  rows: Record<string, TailorRowState>;
  finished: number;
  failed: number;
}

const button: React.CSSProperties = {
  height: 34, padding: '0 14px', borderRadius: 'var(--r-md)', font: '700 12.5px/1 var(--font)', cursor: 'pointer',
};

/**
 * The bulk controls for the Needs action tab: choose which roles, tailor a résumé for each of them
 * (the same in-place PDF tailoring as the job drawer, rescored from the generated file), watch it
 * happen row by row, then approve. Nothing is approved by tailoring: that stays a separate,
 * deliberate click.
 */
export default function BulkTailorBar(p: Props) {
  const done = Object.values(p.rows).filter((r) => r.phase === 'done');
  const improved = done.filter((r) => r.phase === 'done' && r.after != null && r.before != null && r.after > r.before).length;
  const unchanged = done.filter((r) => r.phase === 'done' && r.status === 'unchanged').length;
  const hasRun = Object.keys(p.rows).length > 0;
  const bases = p.resumes.filter((r) => r.type === 'base' && !r.archived);
  const pct = hasRun ? Math.round((p.finished / Math.max(1, Object.keys(p.rows).length)) * 100) : 0;

  return (
    <div
      role="region"
      aria-label="Bulk résumé tailoring"
      style={{
        position: 'sticky', top: 8, zIndex: 5, backdropFilter: 'blur(14px)',
        display: 'flex', flexDirection: 'column', gap: 10, padding: '12px 14px', marginBottom: 12,
        borderRadius: 'var(--r-lg)', background: 'var(--surface-2)', border: '1px solid var(--border-2)', boxShadow: 'var(--shadow-1)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button
          onClick={p.selectedCount === p.totalCount ? p.onClear : p.onSelectAll}
          style={{ ...button, height: 30, background: 'transparent', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '600 12px/1 var(--font)' }}
        >
          {p.selectedCount === p.totalCount ? 'Clear selection' : `Select all ${p.totalCount}`}
        </button>
        <span style={{ font: '700 12.5px/1 var(--font)', color: 'var(--text)' }}>{p.selectedCount} selected</span>
        <div style={{ flex: '1 1 auto' }} />
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, font: '600 11.5px/1 var(--font)', color: 'var(--text-3)' }}>
          Start from
          <select
            aria-label="Résumé to tailor from"
            value={p.baseResumeId}
            onChange={(e) => p.onBaseResumeChange(e.target.value)}
            disabled={p.running}
            style={{ height: 34, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)', font: '600 12px/1 var(--font)', minWidth: 190 }}
          >
            <option value="">Best match for each role</option>
            {bases.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </label>
        {p.running ? (
          <button onClick={p.onCancel} style={{ ...button, background: 'var(--surface-2)', border: '1px solid var(--border-2)', color: 'var(--text)' }}>
            Stop after current
          </button>
        ) : (
          <button
            onClick={p.onTailor}
            disabled={p.selectedCount === 0}
            title="Tailor a résumé for every selected role: only wording your résumé already supports is changed, the PDF layout is untouched, and the ATS score is measured on the generated file."
            style={{
              ...button, background: p.selectedCount ? 'var(--accent)' : 'var(--surface-3)',
              border: `1px solid ${p.selectedCount ? 'var(--accent)' : 'var(--border)'}`,
              color: p.selectedCount ? 'var(--accent-ink)' : 'var(--text-4)', cursor: p.selectedCount ? 'pointer' : 'default',
              display: 'inline-flex', alignItems: 'center', gap: 6,
            }}
          >
            <Icon name="wand" size={13} /> Tailor résumés for {p.selectedCount || '…'}
          </button>
        )}
        <button
          onClick={p.onApprove}
          disabled={p.selectedCount === 0 || p.running || p.approving}
          title="Approve every selected role and release it to the agent with the résumé attached to it."
          style={{
            ...button, background: 'var(--surface-2)', border: '1px solid var(--border-2)',
            color: p.selectedCount && !p.running ? 'var(--text)' : 'var(--text-4)',
            cursor: p.selectedCount && !p.running ? 'pointer' : 'default',
          }}
        >
          Approve {p.selectedCount || '…'} selected
        </button>
        <button
          onClick={p.onApproveAll}
          disabled={p.running || p.approving}
          title="Approve every application waiting for review and release them to the agent."
          style={{ ...button, background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-3)', font: '600 12px/1 var(--font)' }}
        >
          Approve all {p.totalCount}
        </button>
      </div>

      {hasRun && (
        <div role="status" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ height: 4, borderRadius: 999, background: 'var(--surface-3)', overflow: 'hidden' }}>
            <div style={{ width: `${pct}%`, height: '100%', background: 'var(--accent)', transition: 'width .3s var(--ease)' }} />
          </div>
          <div style={{ font: '600 12px/1.4 var(--font)', color: 'var(--text-2)' }}>
            {p.running
              ? `Tailoring ${p.finished} of ${Object.keys(p.rows).length}…`
              : `${done.length} tailored · ${improved} with a higher match${unchanged ? ` · ${unchanged} kept as is (nothing more your résumé supports)` : ''}${p.failed ? ` · ${p.failed} failed` : ''}`}
            {!p.running && done.length > 0 && (
              <button
                onClick={p.onRegenerate}
                style={{ marginLeft: 10, background: 'none', border: 0, padding: 0, color: 'var(--accent)', font: '700 12px/1 var(--font)', cursor: 'pointer' }}
              >
                Regenerate
              </button>
            )}
          </div>
          {!p.running && done.some((r) => r.phase === 'done' && r.after != null) && (
            <div style={{ font: '500 11.5px/1.45 var(--font)', color: 'var(--text-3)' }}>
              Average match {atsPercent(avg(done.map((r) => (r.phase === 'done' ? r.before : null))))}% → {atsPercent(avg(done.map((r) => (r.phase === 'done' ? r.after : null))))}% (measured on each generated PDF).
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function avg(values: (number | null)[]): number {
  const nums = values.filter((v): v is number => v != null);
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
}
