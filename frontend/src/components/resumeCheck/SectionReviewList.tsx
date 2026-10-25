/** Section-by-section review: the rule findings, with the AI's note for that section merged in
 *  once the review lands. The rules stand on their own; the note is additive. */
import { atsPercent } from '@/lib/status';
import type { SectionNote, SectionReview } from '@/types/resumeCheck';
import { SECTION_LABEL, SECTION_ORDER, SECTION_STATUS } from './reportMeta';

export default function SectionReviewList({
  sections, notes,
}: {
  sections: SectionReview[];
  notes: SectionNote[];
}) {
  if (!sections.length) return <p className="rc-empty">No sections were reviewed.</p>;
  const ordered = [...sections].sort((a, b) => SECTION_ORDER.indexOf(a.key) - SECTION_ORDER.indexOf(b.key));

  return (
    <div>
      {ordered.map((s) => {
        const tone = SECTION_STATUS[s.status];
        const sectionNotes = notes.filter((n) => n.section === s.key);
        return (
          <div key={s.key} className="rc-part" data-testid={`section-${s.key}`}>
            <div className="rc-part-head">
              <h3>{s.label || SECTION_LABEL[s.key]}</h3>
              <span className="rc-status" style={{ background: tone.soft, color: 'var(--text)', boxShadow: `inset 0 0 0 1px ${tone.color}` }}>
                {tone.label}
              </span>
              <span className="rc-meta">{atsPercent(s.score)}/100</span>
            </div>
            {s.findings.length ? (
              <ul className="rc-findings">
                {s.findings.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            ) : (
              <p className="rc-empty">No issues found.</p>
            )}
            {sectionNotes.map((n, i) => (
              <p key={i} className="rc-note"><b>AI note</b>{n.note}</p>
            ))}
          </div>
        );
      })}
    </div>
  );
}
