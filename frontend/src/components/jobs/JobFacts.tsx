/**
 * Employer · City, Country · Posted <date> (N days ago) · Work arrangement
 *
 * The line a candidate reads before anything else, on every card and at the top of the
 * drawer. Unknowns are stated ("Posting date unavailable", "Arrangement not stated"), never
 * filled in from another field.
 */
import Icon from '@/components/ui/Icon';
import { WORKPLACE_LABEL, placeLabel, postedInfo, workplaceOf } from '@/lib/jobPlace';
import type { Job } from '@/types/job';

const sep = <span aria-hidden="true" style={{ color: 'var(--jc-text-4)' }}>·</span>;

export default function JobFacts({ job, size = 'card' }: { job: Job; size?: 'card' | 'drawer' }) {
  const place = placeLabel(job);
  const posted = postedInfo(job);
  const arrangement = workplaceOf(job);
  const font = size === 'drawer' ? '500 13px/1.45 var(--font)' : '500 12.5px/1.45 var(--font)';

  return (
    <div
      className="jc-facts"
      style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', columnGap: 7, rowGap: 2, font, color: 'var(--jc-text-2)' }}
    >
      <span style={{ fontWeight: 600, color: 'var(--jc-text)' }}>{job.company}</span>
      {sep}
      <span
        title={job.raw_location && job.raw_location !== place ? `As posted: ${job.raw_location}` : undefined}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
      >
        <Icon name="mappin" size={12} />
        {place}
      </span>
      {sep}
      <time
        dateTime={posted.known ? (job.posted_at ?? job.posted_date ?? undefined) : undefined}
        title={
          posted.known
            ? `${posted.label} — as stated by the source`
            : 'The source did not publish a posting date. CVil-War does not estimate one.'
        }
        style={{ color: posted.known ? undefined : 'var(--jc-text-4)' }}
      >
        {posted.known ? `${posted.label} (${posted.ago})` : posted.label}
      </time>
      {sep}
      <span style={{ color: arrangement === 'unspecified' ? 'var(--jc-text-4)' : undefined }}>
        {WORKPLACE_LABEL[arrangement]}
      </span>
    </div>
  );
}
