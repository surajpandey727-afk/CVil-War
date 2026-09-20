import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import { useRestoreVersion } from '@/hooks/useResumeIntelligence';
import { useAppStore } from '@/store/useAppStore';
import { relativeTime } from '@/lib/status';
import type { ResumeChangeOut, ResumeVersionDetail } from '@/types/resumeIntelligence';

const CHANGE_MARK: Record<string, { symbol: string; color: string }> = {
  added: { symbol: '+', color: 'var(--applied)' },
  removed: { symbol: '−', color: 'var(--rejected)' },
  modified: { symbol: '~', color: 'var(--review)' },
  reordered: { symbol: '↕', color: 'var(--text-3)' },
  rephrased: { symbol: '~', color: 'var(--review)' },
  role_positioning: { symbol: '◆', color: 'var(--accent)' },
  ats_alignment: { symbol: '◆', color: 'var(--accent)' },
  market_signal: { symbol: '◆', color: 'var(--accent)' },
  user_edit: { symbol: '~', color: 'var(--text-3)' },
  ai_suggestion: { symbol: '◆', color: 'var(--accent)' },
  restored: { symbol: '↺', color: 'var(--review)' },
};

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

/**
 * The résumé's version history rendered as a change-log timeline — one entry per commit,
 * each expandable to the individual changes it bundled, each of THOSE expandable to its own
 * before/why/source/evidence. Shared between the master résumé and every role branch.
 */
export default function ChangeLogTimeline({ versions, onCompare }: {
  versions: ResumeVersionDetail[];
  onCompare?: (fromId: string, toId: string) => void;
}) {
  const notify = useAppStore((s) => s.showNotification);
  const restore = useRestoreVersion();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [compareFrom, setCompareFrom] = useState<string | null>(null);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const doRestore = (versionId: string, label: string) => {
    restore.mutate(
      { versionId },
      {
        onSuccess: (v) => notify(`Restored content from ${label} as ${v.version_label}`, 'success'),
        onError: () => notify('Could not restore that version', 'error'),
      },
    );
  };

  const pickForCompare = (id: string) => {
    if (!onCompare) return;
    if (!compareFrom) {
      setCompareFrom(id);
      notify('Pick a second version to compare against', 'info');
      return;
    }
    if (compareFrom === id) {
      setCompareFrom(null);
      return;
    }
    onCompare(compareFrom, id);
    setCompareFrom(null);
  };

  if (versions.length === 0) {
    return (
      <div style={{ ...card, padding: '30px 20px', textAlign: 'center', color: 'var(--text-3)' }}>
        <p style={{ margin: 0, font: '500 12.5px/1.5 var(--font)' }}>No versions yet.</p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {versions.map((v, i) => {
        const isOpen = expanded.has(v.id);
        const isLast = i === versions.length - 1;
        return (
          <div key={v.id} style={{ display: 'flex', gap: 12 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: '0 0 auto' }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: i === 0 ? 'var(--accent)' : 'var(--text-4)', marginTop: 18 }} />
              {!isLast && <span style={{ flex: 1, width: 1, background: 'var(--border)', minHeight: 24 }} />}
            </div>
            <div style={{ flex: 1, minWidth: 0, paddingBottom: 18 }}>
              <div style={{ ...card, padding: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <button onClick={() => toggle(v.id)} style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 0, padding: 0, cursor: 'pointer', textAlign: 'left', flex: '1 1 auto', minWidth: 0 }}>
                    <Icon name={isOpen ? 'chevD' : 'chevR'} size={13} />
                    <span style={{ font: '700 13px/1.2 var(--font)', color: 'var(--text)' }}>{v.version_label}</span>
                    <span style={{ font: '500 11px/1 var(--font)', color: 'var(--text-4)' }}>{relativeTime(v.created_at)}</span>
                    {v.changes.length > 0 && (
                      <span style={{ font: '600 10.5px/1 var(--mono)', color: 'var(--text-3)' }}>
                        {v.changes.length} change{v.changes.length === 1 ? '' : 's'}
                      </span>
                    )}
                  </button>
                  {onCompare && (
                    <button
                      onClick={() => pickForCompare(v.id)}
                      style={{ ...tinyBtn, background: compareFrom === v.id ? 'var(--accent-soft)' : 'var(--surface-2)', color: compareFrom === v.id ? 'var(--accent)' : 'var(--text-3)' }}
                    >
                      {compareFrom === v.id ? 'Selected' : 'Compare'}
                    </button>
                  )}
                  {i !== 0 && (
                    <button onClick={() => doRestore(v.id, v.version_label)} disabled={restore.isPending} style={tinyBtn}>
                      <Icon name="refresh" size={11} /> Restore
                    </button>
                  )}
                </div>

                {!isOpen && v.commit_message && (
                  <p style={{ margin: '6px 0 0 21px', font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)' }}>{v.commit_message}</p>
                )}

                {isOpen && (
                  <div style={{ marginTop: 10, marginLeft: 21, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {v.commit_message && (
                      <p style={{ margin: 0, font: '600 11.5px/1.4 var(--font)', color: 'var(--text-2)' }}>{v.commit_message}</p>
                    )}
                    {v.changes.length === 0 ? (
                      <p style={{ margin: 0, font: '500 11.5px/1.4 var(--font)', color: 'var(--text-4)' }}>No individual changes recorded for this version.</p>
                    ) : (
                      v.changes.map((c) => <ChangeRow key={c.id} change={c} />)
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ChangeRow({ change }: { change: ResumeChangeOut }) {
  const [open, setOpen] = useState(false);
  const mark = CHANGE_MARK[change.change_type] ?? { symbol: '~', color: 'var(--text-3)' };
  return (
    <div style={{ padding: '9px 11px', borderRadius: 'var(--r-sm)', background: 'var(--surface-2)' }}>
      <button onClick={() => setOpen((o) => !o)} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, background: 'none', border: 0, padding: 0, width: '100%', textAlign: 'left', cursor: 'pointer' }}>
        <span style={{ font: '800 13px/1.3 var(--mono)', color: mark.color, flex: '0 0 auto' }}>{mark.symbol}</span>
        <span style={{ flex: '1 1 auto', minWidth: 0 }}>
          <span style={{ font: '600 12px/1.4 var(--font)', color: 'var(--text-2)' }}>
            {change.after_text || change.before_text || change.section}
          </span>
          <span style={{ display: 'block', font: '500 10.5px/1.3 var(--mono)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.03em', marginTop: 2 }}>
            {change.section} · {change.change_type.replace(/_/g, ' ')}
          </span>
        </span>
      </button>
      {open && (
        <div style={{ marginTop: 8, marginLeft: 21, display: 'flex', flexDirection: 'column', gap: 6, font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
          {change.before_text && (
            <div><strong style={{ color: 'var(--text-4)' }}>Before:</strong> <span style={{ textDecoration: 'line-through' }}>{change.before_text}</span></div>
          )}
          {change.after_text && <div><strong style={{ color: 'var(--text-4)' }}>After:</strong> {change.after_text}</div>}
          {change.reason && <div><strong style={{ color: 'var(--text-4)' }}>Why:</strong> {change.reason}</div>}
          {change.evidence && <div><strong style={{ color: 'var(--text-4)' }}>Evidence:</strong> {change.evidence}</div>}
        </div>
      )}
    </div>
  );
}

const tinyBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, height: 24, padding: '0 9px',
  borderRadius: 999, background: 'var(--surface-2)', border: '1px solid var(--border)',
  color: 'var(--text-3)', font: '600 10.5px/1 var(--font)', cursor: 'pointer', flex: '0 0 auto',
};
