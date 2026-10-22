/** Role selection for the Skill Radar: pick the target titles to aggregate demand across.
 *
 *  Grouped by family so the list scans, with select-all-in-family and a clear-all. The chips are
 *  the same visual language as the rest of the app (accent-soft when on), kept here rather than
 *  reaching into the Jobs page's private Chip so this component stands alone.
 */
import { useMemo } from 'react';

type Family = 'Product' | 'AI / ML engineering' | 'Data & analytics' | 'Architecture & consulting';

function familyOf(title: string): Family {
  const t = title.toLowerCase();
  if (/(product manager|product owner|product analyst|apm)/.test(t)) return 'Product';
  if (/(scientist|analyst|analytics)/.test(t)) return 'Data & analytics';
  if (/(architect|consultant|strategy)/.test(t)) return 'Architecture & consulting';
  return 'AI / ML engineering';
}

const FAMILY_ORDER: Family[] = [
  'Product', 'AI / ML engineering', 'Data & analytics', 'Architecture & consulting',
];

export default function RolePicker({
  roles, selected, onToggle, onSetMany, onClear,
}: {
  roles: string[];
  selected: string[];
  onToggle: (title: string) => void;
  onSetMany: (titles: string[]) => void;
  onClear: () => void;
}) {
  const grouped = useMemo(() => {
    const m = new Map<Family, string[]>();
    for (const fam of FAMILY_ORDER) m.set(fam, []);
    for (const r of roles) m.get(familyOf(r))!.push(r);
    return m;
  }, [roles]);

  const sel = new Set(selected);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ font: '600 12px/1 var(--mono)', letterSpacing: '.1em', color: 'var(--text-4)' }}>
          {selected.length} ROLE{selected.length === 1 ? '' : 'S'} SELECTED
        </span>
        {selected.length > 0 && (
          <button
            onClick={onClear}
            title="Deselect every role."
            style={{
              background: 'none', border: 0, cursor: 'pointer', padding: 0,
              font: '600 11px/1 var(--font)', color: 'var(--accent-2)',
            }}
          >
            Clear all
          </button>
        )}
      </div>

      {FAMILY_ORDER.map((fam) => {
        const titles = grouped.get(fam) ?? [];
        if (!titles.length) return null;
        const allOn = titles.every((t) => sel.has(t));
        return (
          <div key={fam}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 7 }}>
              <span style={{ font: '700 11px/1 var(--font)', color: 'var(--text-3)' }}>{fam}</span>
              <button
                onClick={() => onSetMany(allOn
                  ? selected.filter((t) => !titles.includes(t))
                  : [...new Set([...selected, ...titles])])}
                style={{
                  background: 'none', border: 0, cursor: 'pointer', padding: 0,
                  font: '600 10px/1 var(--mono)', color: 'var(--text-4)',
                }}
              >
                {allOn ? 'none' : 'all'}
              </button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
              {titles.map((t) => {
                const on = sel.has(t);
                return (
                  <button
                    key={t} onClick={() => onToggle(t)} aria-pressed={on}
                    style={{
                      height: 30, padding: '0 12px', borderRadius: 999, cursor: 'pointer',
                      font: '600 12px/1 var(--font)',
                      border: `1px solid ${on ? 'var(--accent-line)' : 'var(--border)'}`,
                      background: on ? 'var(--accent-soft)' : 'var(--surface-2)',
                      color: on ? 'var(--accent-2)' : 'var(--text-3)',
                      transition: 'all .12s var(--ease)',
                    }}
                  >
                    {t}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
