/** Matched skills with their verbatim résumé evidence, and the ranked gaps.
 *
 *  Evidence is quoted, never paraphrased — the point is that the person can see exactly which
 *  line earned the match. Gaps keep the backend's ranking (must-haves first, then by how often
 *  UK jobs ask for them) and state demand as a count out of the jobs actually scanned. With no
 *  corpus there is no count to give, so it says so instead of inventing a share.
 */
import type { MatchedSkill, MissingSkill } from '@/types/resumeCheck';

export function MatchedSkills({ skills }: { skills: MatchedSkill[] }) {
  if (!skills.length) {
    return <p className="rc-empty">None of the target&apos;s skills were found in this résumé yet.</p>;
  }
  return (
    <ul className="rc-list">
      {skills.map((s) => (
        <li key={s.key}>
          <div className="rc-skill-name">
            {s.label}
            {s.must_have && <span className="rc-tag" data-k="must">Must-have</span>}
          </div>
          {s.evidence.length === 0 ? (
            <p className="rc-empty" style={{ marginTop: 4 }}>Matched, but no single line to quote.</p>
          ) : (
            s.evidence.map((e, i) => (
              <figure key={i} className="rc-quote">
                <q>{e.quote}</q>
                <figcaption>From {e.section}</figcaption>
              </figure>
            ))
          )}
        </li>
      ))}
    </ul>
  );
}

function demandText(n: number, scanned: number): string {
  if (scanned <= 0) return 'No UK job corpus yet';
  return `Asked for in ${n} of ${scanned} UK jobs`;
}

function GapList({ title, skills, scanned }: { title: string; skills: MissingSkill[]; scanned: number }) {
  return (
    <div>
      <h3>{title} <span className="rc-meta">({skills.length})</span></h3>
      {skills.length === 0 ? (
        <p className="rc-empty">Nothing missing here.</p>
      ) : (
        <ol className="rc-list" style={{ gap: 12 }}>
          {skills.map((s, i) => (
            <li key={s.key} className="rc-gap" data-testid="missing-skill">
              <span className="rank" aria-hidden="true">{i + 1}</span>
              <span className="what">{s.label}</span>
              <span className="demand">{demandText(s.uk_demand, scanned)}</span>
              {scanned > 0 && (
                <span className="meter" aria-hidden="true">
                  <span style={{ width: `${Math.min(100, (s.uk_demand / scanned) * 100)}%` }} />
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function MissingSkills({ skills, scanned }: { skills: MissingSkill[]; scanned: number }) {
  if (!skills.length) {
    return <p className="rc-empty">No missing skills — the résumé covers everything this target lists.</p>;
  }
  // filter() keeps the backend's ranking within each group.
  const must = skills.filter((s) => s.must_have);
  const nice = skills.filter((s) => !s.must_have);
  return (
    <div className="rc-gaps">
      <GapList title="Must-haves" skills={must} scanned={scanned} />
      <GapList title="Nice-to-haves" skills={nice} scanned={scanned} />
    </div>
  );
}
