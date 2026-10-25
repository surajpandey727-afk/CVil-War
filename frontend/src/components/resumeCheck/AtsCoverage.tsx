/** ATS keyword coverage: which of the target's screening keywords the résumé already uses. */
import { atsPercent } from '@/lib/status';
import type { AtsKeywords } from '@/types/resumeCheck';

export default function AtsCoverage({ ats }: { ats: AtsKeywords }) {
  if (ats.total === 0) {
    return <p className="rc-empty">This target has no ATS keyword list to check against.</p>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <p style={{ margin: 0, font: '500 13px/1.4 var(--font)', color: 'var(--text-2)' }}>
        <strong style={{ font: '800 26px/1 var(--font)', color: 'var(--text)', marginRight: 8 }}>{atsPercent(ats.coverage)}%</strong>
        {ats.found.length} of {ats.total} keywords found
      </p>
      <div>
        <h3>Found</h3>
        {ats.found.length ? (
          <ul className="rc-chips" data-k="found" aria-label="Keywords found">
            {ats.found.map((k) => <li key={k}>{k}</li>)}
          </ul>
        ) : <p className="rc-empty">None yet.</p>}
      </div>
      <div>
        <h3>Missing</h3>
        {ats.missing.length ? (
          <ul className="rc-chips" data-k="missing" aria-label="Keywords missing">
            {ats.missing.map((k) => <li key={k}>{k}</li>)}
          </ul>
        ) : <p className="rc-empty">Every keyword is covered.</p>}
      </div>
    </div>
  );
}
