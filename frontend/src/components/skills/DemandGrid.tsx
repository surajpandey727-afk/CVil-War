/** The aggregated in-demand skills across the selected roles, grouped by category.
 *
 *  Each skill shows how strongly it is wanted (a bar scaled to the top skill's demand), how many
 *  of the chosen roles ask for it, and whether it is a must-have, an ATS keyword, or carries a
 *  live count from the candidate's own job corpus. Optionally, a score result marks which skills
 *  the résumé already covers — so this same grid doubles as the gap view after a match.
 */
import type { AggregatedSkill } from '@/types/skills';

export default function DemandGrid({
  skills, categories, corpusUsed, coverage,
}: {
  skills: AggregatedSkill[];
  categories: string[];
  corpusUsed: boolean;
  /** key -> present, when a résumé has been scored. Undefined before any match. */
  coverage?: Map<string, boolean>;
}) {
  if (!skills.length) return null;
  const maxDemand = Math.max(...skills.map((s) => s.demand), 1);
  const byCat = new Map<string, AggregatedSkill[]>();
  for (const s of skills) {
    if (!byCat.has(s.category)) byCat.set(s.category, []);
    byCat.get(s.category)!.push(s);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {categories.filter((c) => byCat.has(c)).map((cat) => (
        <div key={cat}>
          <div style={{ font: '700 11px/1 var(--font)', color: 'var(--text-3)', marginBottom: 9, letterSpacing: '.02em' }}>
            {cat}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            {byCat.get(cat)!.map((s) => (
              <SkillRow key={s.key} skill={s} max={maxDemand} corpusUsed={corpusUsed} present={coverage?.get(s.key)} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function SkillRow({
  skill, max, corpusUsed, present,
}: {
  skill: AggregatedSkill;
  max: number;
  corpusUsed: boolean;
  present?: boolean;
}) {
  const pct = Math.round((skill.demand / max) * 100);
  // When scored: green if covered, amber if a missing must-have, muted otherwise.
  const scored = present !== undefined;
  const barColor = scored
    ? present ? 'var(--applied)' : skill.must_have ? 'var(--review)' : 'var(--border-3)'
    : 'var(--accent)';

  return (
    <div
      title={
        `${skill.roles_wanting} of the selected roles want ${skill.label}.` +
        (skill.must_have ? ' Core requirement.' : '') +
        (skill.ats ? ' ATS keyword — mirror it verbatim.' : '') +
        (skill.corpus_count != null ? ` Seen in ${skill.corpus_count} of your stored jobs.` : '') +
        (scored ? (present ? ' Present in this résumé.' : ' Missing from this résumé.') : '')
      }
      style={{
        display: 'grid', gridTemplateColumns: '1fr auto', gap: 10, alignItems: 'center',
        padding: '7px 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
        border: '1px solid var(--border)', opacity: scored && !present && !skill.must_have ? 0.72 : 1,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5, flexWrap: 'wrap' }}>
          {scored && (
            <span style={{
              width: 14, height: 14, borderRadius: 4, flex: '0 0 auto', display: 'grid', placeItems: 'center',
              background: present ? 'var(--applied-soft)' : 'transparent',
              border: present ? 'none' : `1.5px solid ${skill.must_have ? 'var(--review)' : 'var(--border-3)'}`,
              color: 'var(--applied)', font: '800 10px/1 var(--font)',
            }}>{present ? '✓' : ''}</span>
          )}
          <span style={{ font: '600 12.5px/1 var(--font)', color: 'var(--text-2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {skill.label}
          </span>
          {skill.must_have && <Tag text="MUST" tone="review" />}
          {skill.ats && <Tag text="ATS" tone="accent" />}
          {corpusUsed && skill.corpus_count != null && (
            <span style={{ font: '600 9.5px/1 var(--mono)', color: 'var(--applied)' }}>
              {skill.corpus_count}&times; live
            </span>
          )}
        </div>
        <div style={{ height: 5, borderRadius: 3, background: 'var(--surface-3)', overflow: 'hidden' }}>
          {/* Scale on the transform, not width, so the bar animates on the GPU without
              triggering layout on every selection change. */}
          <div style={{ width: '100%', height: '100%', background: barColor, borderRadius: 3, transformOrigin: 'left', transform: `scaleX(${pct / 100})`, transition: 'transform .3s var(--ease)' }} />
        </div>
      </div>
      <span style={{ font: '600 10px/1 var(--mono)', color: 'var(--text-4)', whiteSpace: 'nowrap' }}>
        {skill.roles_wanting} role{skill.roles_wanting === 1 ? '' : 's'}
      </span>
    </div>
  );
}

function Tag({ text, tone }: { text: string; tone: 'review' | 'accent' }) {
  const color = tone === 'review' ? 'var(--review)' : 'var(--accent-2)';
  const bg = tone === 'review' ? 'var(--review-soft)' : 'var(--accent-soft)';
  return (
    <span style={{ font: '700 8.5px/1 var(--mono)', letterSpacing: '.06em', color, background: bg, padding: '3px 5px', borderRadius: 4 }}>
      {text}
    </span>
  );
}
