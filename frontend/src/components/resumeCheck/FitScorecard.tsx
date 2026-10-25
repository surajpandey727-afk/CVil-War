/** The headline fit score, and the arithmetic behind it.
 *
 *  A score nobody can audit is a score nobody trusts, so the card shows its working: a stacked
 *  bar where each segment is that component's contribution (weight × score), a ledger with the
 *  same numbers as text (the accessible reading of the bar), and the backend's formula string.
 */
import { atsPercent } from '@/lib/status';
import type { CheckTarget, FitScore } from '@/types/resumeCheck';
import { BAND, segmentColor } from './reportMeta';

/** Contribution in points out of 100, one decimal — small components still register. */
function points(weight: number, score: number): string {
  return (weight * score * 100).toFixed(1);
}

function targetLine(target: CheckTarget): string {
  if (target.kind === 'job') return target.company ? `${target.title} at ${target.company}` : target.title;
  return target.role_titles.length ? target.role_titles.join(', ') : target.title;
}

export default function FitScorecard({
  score, target, resumeName,
}: {
  score: FitScore;
  target: CheckTarget;
  resumeName: string;
}) {
  const band = BAND[score.band];
  const pct = atsPercent(score.overall);

  return (
    <div className="rc-panel" aria-labelledby="rc-fit-h">
      <h2 id="rc-fit-h" className="rc-label" style={{ margin: '0 0 14px' }}>Overall fit</h2>
      <div className="rc-score-top">
        <span className="rc-big" style={{ color: band.color }}>
          {pct}<small>/100</small>
        </span>
        <span className="rc-band" style={{ background: band.soft, color: 'var(--text)', boxShadow: `inset 0 0 0 1px ${band.color}` }}>
          {band.label}
        </span>
      </div>
      <p className="rc-target">
        <strong>{resumeName}</strong> against{' '}
        {target.kind === 'job' ? 'the job ' : 'the roles '}
        <strong>{targetLine(target)}</strong>. {band.note}
      </p>

      {/* Visual only — the ledger below carries the same numbers for assistive tech. */}
      <div className="rc-bar" aria-hidden="true">
        {score.components.map((c, i) => (
          <span
            key={c.key}
            title={`${c.label}: ${points(c.weight, c.score)} points`}
            style={{ width: `${Math.max(0, c.weight * c.score * 100)}%`, background: segmentColor(i) }}
          />
        ))}
      </div>

      <table className="rc-ledger">
        <caption className="rc-sr">How the overall fit score is calculated</caption>
        <thead>
          <tr>
            <th scope="col">Component</th>
            <th scope="col" className="num">Weight</th>
            <th scope="col" className="num">Score</th>
            <th scope="col" className="num">Points</th>
          </tr>
        </thead>
        <tbody>
          {score.components.map((c, i) => (
            <tr key={c.key}>
              <td>
                <span className="rc-swatch" style={{ background: segmentColor(i) }} aria-hidden="true" />
                {c.label}
                <span className="rc-detail">{c.detail}</span>
              </td>
              <td className="num">{atsPercent(c.weight)}%</td>
              <td className="num">{atsPercent(c.score)}%</td>
              <td className="num">{points(c.weight, c.score)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3}>Overall</td>
            <td className="num">{pct}</td>
          </tr>
        </tfoot>
      </table>

      <p className="rc-formula">
        <span className="rc-sr">Formula: </span>
        {score.formula}
      </p>
    </div>
  );
}
