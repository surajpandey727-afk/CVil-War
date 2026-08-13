import { useEffect, useMemo, useState } from 'react';

import Icon from '@/components/ui/Icon';
import { useSettings, useUpdateSettings } from '@/hooks/useSettings';
import { useAppStore } from '@/store/useAppStore';
import { useDiscoveryStore } from '@/store/useDiscoveryStore';
import { ROLE_FAMILIES, ROLE_TARGETS, fitStars } from '@/lib/roleTargets';
import type { RoleTargetRecord } from '@/types/settings';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

type TierFilter = 'all' | 'five' | 'fourPlus' | 'active';

const TIER_FILTERS: { key: TierFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'five', label: '5 star' },
  { key: 'fourPlus', label: '4+ star' },
  { key: 'active', label: 'Active' },
];

/** Seed the table from the shipped assessment the first time a user opens this page. */
function seedTargets(): RoleTargetRecord[] {
  return ROLE_TARGETS.map((r) => ({
    title: r.title, fit: r.fit, why: r.why, family: r.family, active: r.fit >= 4,
  }));
}

/**
 * Role targets — the source of truth for what the agent searches for.
 *
 * Persisted server-side on `UserSettings.role_targets` so scheduled worker-side discovery
 * reads the same list the operator sees, and the local discovery store is kept in step so the
 * Jobs screen filters without a round trip.
 */
export default function RoleTargetsPage() {
  const notify = useAppStore((s) => s.showNotification);
  const { data: settings, isLoading } = useSettings();
  const update = useUpdateSettings();
  const setTitles = useDiscoveryStore((s) => s.setTitles);

  const [rows, setRows] = useState<RoleTargetRecord[]>([]);
  const [filter, setFilter] = useState<TierFilter>('all');
  const [newTitle, setNewTitle] = useState('');

  useEffect(() => {
    if (!settings) return;
    setRows(settings.role_targets.length ? settings.role_targets : seedTargets());
  }, [settings]);

  const dirty = useMemo(
    () => JSON.stringify(rows) !== JSON.stringify(settings?.role_targets ?? []),
    [rows, settings],
  );

  const visible = useMemo(() => rows.filter((r) => {
    if (filter === 'five') return r.fit === 5;
    if (filter === 'fourPlus') return r.fit >= 4;
    if (filter === 'active') return r.active;
    return true;
  }), [rows, filter]);

  const activeCount = rows.filter((r) => r.active).length;

  const save = () => {
    update.mutate(
      { role_targets: rows },
      {
        onSuccess: () => {
          setTitles(rows.filter((r) => r.active).map((r) => r.title));
          notify(`${activeCount} role targets saved`, 'success');
        },
        onError: () => notify('Could not save the role targets', 'error'),
      },
    );
  };

  const patchRow = (title: string, p: Partial<RoleTargetRecord>) =>
    setRows((rs) => rs.map((r) => (r.title === title ? { ...r, ...p } : r)));

  const addRow = () => {
    const title = newTitle.trim();
    if (!title) return;
    if (rows.some((r) => r.title.toLowerCase() === title.toLowerCase())) {
      notify('That title is already in the table', 'warning');
      return;
    }
    setRows((rs) => [{ title, fit: 3, why: 'Added manually', family: 'engineering', active: true }, ...rs]);
    setNewTitle('');
  };

  if (isLoading) {
    return <div style={{ ...card, padding: 18, color: 'var(--text-3)', font: '500 13px/1.4 var(--font)' }}>Loading role targets…</div>;
  }

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1320 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 auto', minWidth: 240 }}>
          <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Role targets</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
            {activeCount} of {rows.length} titles active. Active titles drive every search, alert and auto-apply decision.
          </p>
        </div>
        <button
          onClick={save} disabled={!dirty || update.isPending}
          style={{
            height: 36, padding: '0 16px', borderRadius: 'var(--r-md)',
            background: dirty ? 'var(--accent)' : 'var(--surface-2)',
            border: `1px solid ${dirty ? 'var(--accent)' : 'var(--border)'}`,
            color: dirty ? 'var(--accent-ink)' : 'var(--text-3)',
            font: '700 12.5px/1 var(--font)', cursor: dirty ? 'pointer' : 'default',
          }}
        >
          {update.isPending ? 'Saving…' : dirty ? 'Save targets' : 'Saved'}
        </button>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        {TIER_FILTERS.map((f) => (
          <button
            key={f.key} onClick={() => setFilter(f.key)} aria-pressed={filter === f.key}
            style={{
              height: 28, padding: '0 11px', borderRadius: 999, cursor: 'pointer',
              font: '600 11.5px/1 var(--font)',
              border: `1px solid ${filter === f.key ? 'var(--accent-line)' : 'var(--border)'}`,
              background: filter === f.key ? 'var(--accent-soft)' : 'var(--surface-2)',
              color: filter === f.key ? 'var(--accent)' : 'var(--text-3)',
            }}
          >
            {f.label}
          </button>
        ))}
        <div style={{ flex: '1 1 auto' }} />
        <input
          value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addRow(); }}
          placeholder="Add a role title"
          style={{
            height: 32, width: 220, padding: '0 11px', borderRadius: 'var(--r-md)',
            background: 'var(--surface-3)', border: '1px solid var(--border)',
            color: 'var(--text)', font: '500 12.5px/1 var(--font)', outline: 'none',
          }}
        />
        <button
          onClick={addRow}
          style={{ height: 32, padding: '0 13px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-2)', font: '700 12px/1 var(--font)', cursor: 'pointer' }}
        >
          Add
        </button>
      </div>

      <div style={{ ...card, overflow: 'hidden' }}>
        <div style={{ ...gridRow, padding: '12px 16px', background: 'var(--surface-3)', borderBottom: '1px solid var(--border)' }}>
          <span style={th}>ON</span>
          <span style={th}>ROLE</span>
          <span style={th}>FIT</span>
          <span style={th}>FAMILY</span>
          <span style={th}>WHY</span>
          <span style={{ ...th, textAlign: 'right' }} />
        </div>
        {visible.map((r) => (
          <div key={r.title} style={{ ...gridRow, padding: '11px 16px', borderBottom: '1px solid var(--border)' }}>
            <button
              onClick={() => patchRow(r.title, { active: !r.active })} aria-label={`Toggle ${r.title}`}
              style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', display: 'grid', placeItems: 'center', justifyContent: 'start' }}
            >
              <span
                style={{
                  display: 'grid', placeItems: 'center', width: 17, height: 17, borderRadius: 5,
                  border: `1px solid ${r.active ? 'var(--accent)' : 'var(--border-3)'}`,
                  background: r.active ? 'var(--accent)' : 'transparent',
                }}
              >
                {r.active && <Icon name="check" size={11} sw={3.4} />}
              </span>
            </button>
            <span style={{ font: '600 13px/1.3 var(--font)', color: r.active ? 'var(--text)' : 'var(--text-3)' }}>{r.title}</span>
            <span style={{ font: '500 13px/1 var(--font)', color: 'var(--review)', letterSpacing: '.06em' }}>{fitStars(r.fit)}</span>
            <select
              value={r.family} aria-label={`Family for ${r.title}`}
              onChange={(e) => patchRow(r.title, { family: e.target.value as RoleTargetRecord['family'] })}
              style={{ height: 28, padding: '0 8px', borderRadius: 'var(--r-sm)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-2)', font: '600 11.5px/1 var(--font)' }}
            >
              {(Object.keys(ROLE_FAMILIES) as (keyof typeof ROLE_FAMILIES)[]).map((f) => (
                <option key={f} value={f}>{ROLE_FAMILIES[f].short}</option>
              ))}
            </select>
            <span style={{ font: '500 12px/1.4 var(--font)', color: 'var(--text-3)' }}>{r.why}</span>
            <button
              onClick={() => setRows((rs) => rs.filter((x) => x.title !== r.title))}
              aria-label={`Remove ${r.title}`}
              style={{ justifySelf: 'end', width: 28, height: 28, borderRadius: 'var(--r-sm)', background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-4)', cursor: 'pointer', display: 'grid', placeItems: 'center' }}
            >
              <Icon name="x" size={13} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

const gridRow: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '36px 1.8fr 110px 96px 2.2fr 40px',
  gap: 12,
  alignItems: 'center',
};

const th: React.CSSProperties = {
  font: '600 10px/1 var(--mono)', letterSpacing: '.13em', color: 'var(--text-4)',
};
