/** Score a résumé against the selected roles and read the result against the 60-70% band.
 *
 *  The owner's bar: 60-70% is "decent - most skills covered", above is strong, below is a real
 *  gap. The panel shows the headline coverage, the separate must-have coverage (a strong overall
 *  score can still hide a missing core requirement), and the highest-value skills to add next.
 */
import type { Resume } from '@/types/resume';
import type { SkillScoreResponse, SkillHit } from '@/types/skills';

const BAND = {
  strong: { label: 'Strong match', color: 'var(--applied)', soft: 'var(--applied-soft)', note: 'You cover the skills these roles screen for.' },
  decent: { label: 'Decent - most covered', color: 'var(--review)', soft: 'var(--review-soft)', note: 'Over the 60% bar. Close a few gaps below to pull clear.' },
  gap: { label: 'Below the bar', color: 'var(--rejected)', soft: 'var(--rejected-soft)', note: 'Under 60%. The additions below move the needle most.' },
} as const;

export default function ScorePanel({
  resumes, selectedResumeId, onSelectResume, onRun, running, result, disabled,
}: {
  resumes: Resume[];
  selectedResumeId: string;
  onSelectResume: (id: string) => void;
  onRun: () => void;
  running: boolean;
  result: SkillScoreResponse | null;
  disabled: boolean;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div className="jc-input" style={{ flex: '1 1 220px', height: 38, minWidth: 0 }}>
          <select
            aria-label="Choose a résumé to score"
            value={selectedResumeId}
            onChange={(e) => onSelectResume(e.target.value)}
            style={{ flex: 1, minWidth: 0, background: 'transparent', border: 0, outline: 'none', color: 'var(--text)', font: '600 12.5px/1 var(--font)' }}
          >
            <option value="">Choose a résumé…</option>
            {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </div>
        <button
          onClick={onRun}
          disabled={disabled || running || !selectedResumeId}
          className="jc-btn jc-btn-primary"
          title={disabled ? 'Select at least one role first' : 'Score this résumé against the selected roles'}
          style={{ height: 38, padding: '0 18px', opacity: disabled || !selectedResumeId ? 0.55 : 1 }}
        >
          {running ? 'Scoring…' : 'Run match'}
        </button>
      </div>

      {result && <Result result={result} />}
    </div>
  );
}

function Result({ result }: { result: SkillScoreResponse }) {
  const band = BAND[result.band];
  const pct = Math.round(result.score * 100);
  const mustPct = Math.round(result.must_have_score * 100);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Headline gauge */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', padding: 16, borderRadius: 'var(--r-lg)', background: band.soft, border: `1px solid ${band.color}` }}>
        <div style={{ position: 'relative', width: 84, height: 84, flex: '0 0 auto' }}>
          <svg viewBox="0 0 84 84" style={{ transform: 'rotate(-90deg)' }}>
            <circle cx="42" cy="42" r="36" fill="none" stroke="var(--surface-3)" strokeWidth="8" />
            <circle cx="42" cy="42" r="36" fill="none" stroke={band.color} strokeWidth="8"
              strokeLinecap="round" strokeDasharray={`${(pct / 100) * 226} 226`} />
          </svg>
          <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center' }}>
            <span style={{ font: '800 22px/1 var(--font)', color: band.color }}>{pct}%</span>
          </div>
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ font: '700 14px/1.2 var(--font)', color: 'var(--text)' }}>{band.label}</div>
          <div style={{ font: '500 12px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 4 }}>{band.note}</div>
          <div style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)', marginTop: 8 }}>
            {result.matched_count}/{result.total_count} skills · must-haves {mustPct}%
          </div>
        </div>
      </div>

      {/* Top skills to add */}
      {result.top_to_add.length > 0 && (
        <div>
          <div style={{ font: '700 12px/1 var(--font)', color: 'var(--text-2)', marginBottom: 9 }}>
            Add these next — highest impact first
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {result.top_to_add.map((h, i) => <AddRow key={h.key} hit={h} rank={i + 1} />)}
          </div>
          <div style={{ font: '500 11px/1.5 var(--font)', color: 'var(--text-4)', marginTop: 10 }}>
            Only add a skill you can honestly evidence — the point is to surface the real gaps and
            mirror the wording these roles screen for, not to pad the résumé.
          </div>
        </div>
      )}
    </div>
  );
}

function AddRow({ hit, rank }: { hit: SkillHit; rank: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 11px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
      <span style={{ font: '700 11px/1 var(--mono)', color: 'var(--text-4)', width: 16 }}>{rank}</span>
      <span style={{ flex: 1, font: '600 12.5px/1 var(--font)', color: 'var(--text-2)' }}>{hit.label}</span>
      {hit.must_have && (
        <span style={{ font: '700 8.5px/1 var(--mono)', letterSpacing: '.06em', color: 'var(--review)', background: 'var(--review-soft)', padding: '3px 5px', borderRadius: 4 }}>MUST</span>
      )}
      {hit.ats && (
        <span style={{ font: '700 8.5px/1 var(--mono)', letterSpacing: '.06em', color: 'var(--accent-2)', background: 'var(--accent-soft)', padding: '3px 5px', borderRadius: 4 }}>ATS</span>
      )}
      <span style={{ font: '600 10px/1 var(--mono)', color: 'var(--text-4)' }}>
        {hit.roles_wanting} role{hit.roles_wanting === 1 ? '' : 's'}
      </span>
    </div>
  );
}
