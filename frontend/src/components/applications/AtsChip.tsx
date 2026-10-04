import Icon from '@/components/ui/Icon';
import { atsColor, atsPercent } from '@/lib/status';
import type { ApplicationScoreItem } from '@/types/ats';

interface Props {
  /** The live evaluation for this row, when the batch score has arrived. */
  item?: ApplicationScoreItem;
  /** The score saved on the application (its own résumé's), used until the live one arrives. */
  saved: number | null;
  loading: boolean;
}

/** One line a person can read in a tooltip: which résumé, and what is holding the match back. */
function explain(item: ApplicationScoreItem): string {
  const s = item.summary;
  const via = item.scored_with
    ? item.scored_with.source === 'attached'
      ? `Scored with the attached résumé “${item.scored_with.resume_name}”.`
      : `No résumé attached: scored with your best match, “${item.scored_with.resume_name}”.`
    : '';
  if (!s) return via;
  const parts = [
    via,
    `${s.band}. File parsing ${atsPercent(s.parsing)}%, shortlist readiness ${atsPercent(s.shortlist)}%.`,
    s.top_gaps.length ? `No evidence in the résumé for: ${s.top_gaps.join(', ')}.` : '',
  ];
  return parts.filter(Boolean).join(' ');
}

/**
 * The ATS match for one application row, always present: a number with its colour, a reason when
 * there cannot be one ("no job description"), or a quiet "scoring" while the batch is in flight.
 * A row never silently shows nothing.
 */
export default function AtsChip({ item, saved, loading }: Props) {
  if (item?.scored && item.ats_score != null) {
    const pct = atsPercent(item.ats_score);
    const viaBest = item.scored_with?.source !== 'attached';
    return (
      <span
        title={explain(item)}
        data-testid="ats-chip"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 5, font: '700 12px/1 var(--mono)', color: atsColor(pct) }}
      >
        {viaBest && <Icon name="wand" size={11} />}
        ATS {pct}%
      </span>
    );
  }
  if (saved != null) {
    const pct = atsPercent(saved);
    return (
      <span data-testid="ats-chip" style={{ font: '700 12px/1 var(--mono)', color: atsColor(pct) }}>
        ATS {pct}%
      </span>
    );
  }
  if (loading) {
    return <span data-testid="ats-chip" style={{ font: '600 11px/1 var(--font)', color: 'var(--text-4)' }}>scoring…</span>;
  }
  return (
    <span
      data-testid="ats-chip"
      title={item?.reason || 'No match score yet'}
      style={{ font: '600 11px/1 var(--font)', color: 'var(--text-4)' }}
    >
      {item?.reason?.includes('description') ? 'No description' : 'No score'}
    </span>
  );
}
