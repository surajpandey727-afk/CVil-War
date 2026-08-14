import Icon from '@/components/ui/Icon';
import type { CompanyProfile } from '@/types/company';

/**
 * What is actually known about the employer.
 *
 * Under the zero-cost constraint most of a company profile is genuinely unobtainable: no free
 * source in this stack carries headcount, headquarters or company type. The panel therefore
 * leads with what is real — the name, the official site where one can be established, and
 * their other open roles — and then names what could not be found, rather than rendering a
 * row of blanks that reads as a thin profile.
 *
 * The website is never guessed from the company name. A confident dead link on the page
 * someone is using to decide whether to apply is worse than an honest absence.
 */
export default function CompanyPanel({
  profile,
  onOpenJob,
}: {
  profile: CompanyProfile;
  onOpenJob: (jobId: string) => void;
}) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <span style={{
          width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center',
          background: 'var(--surface-3)', color: 'var(--text-3)',
        }}>
          <Icon name="building" size={16} />
        </span>
        <div style={{ minWidth: 0 }}>
          <div style={{ font: '700 13.5px/1.25 var(--font)' }}>{profile.name}</div>
          {profile.industry ? (
            <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 2 }}>
              {profile.industry}
            </div>
          ) : (
            <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-4)', marginTop: 2 }}>
              Industry not published by this source
            </div>
          )}
        </div>
      </div>

      {profile.description && (
        <p style={{ margin: '0 0 12px', font: '500 12px/1.55 var(--font)', color: 'var(--text-2)' }}>
          {profile.description}
        </p>
      )}

      {profile.website ? (
        <a
          href={profile.website}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 7, height: 32, padding: '0 13px',
            borderRadius: 'var(--r-md)', textDecoration: 'none', background: 'var(--surface-2)',
            border: '1px solid var(--border)', color: 'var(--text-2)',
            font: '700 12px/1 var(--font)', marginBottom: 12,
          }}
        >
          Visit company website <Icon name="ext" size={13} />
        </a>
      ) : (
        <div style={{
          padding: '10px 12px', marginBottom: 12, borderRadius: 'var(--r-md)',
          background: 'var(--surface-2)', border: '1px solid var(--border)',
          font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)',
        }}>
          <strong style={{ color: 'var(--text-2)' }}>Company website unavailable.</strong>{' '}
          {profile.unavailable_reason}
        </div>
      )}

      <div style={{ marginBottom: 12 }}>
        <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)', textTransform: 'uppercase', marginBottom: 7 }}>
          Other open roles
        </div>
        {profile.other_jobs_count === 0 ? (
          // Zero is a real answer and the common one — most employers in a personal job
          // cache have exactly one posting.
          <div style={{ font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
            No other roles from {profile.name} in your list yet.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {profile.other_jobs.map((job) => (
              <button
                key={job.job_id}
                onClick={() => onOpenJob(job.job_id)}
                style={{
                  display: 'flex', alignItems: 'baseline', gap: 8, width: '100%',
                  padding: '8px 10px', borderRadius: 'var(--r-md)', cursor: 'pointer',
                  background: 'var(--surface-2)', border: '1px solid var(--border)',
                  color: 'inherit', textAlign: 'left',
                }}
              >
                <span style={{ flex: '1 1 auto', minWidth: 0, font: '600 11.5px/1.4 var(--font)', color: 'var(--text-2)' }}>
                  {job.title}
                </span>
                {job.location && (
                  <span style={{ flex: '0 0 auto', font: '500 10.5px/1.4 var(--font)', color: 'var(--text-4)' }}>
                    {job.location}
                  </span>
                )}
              </button>
            ))}
            {profile.other_jobs_count > profile.other_jobs.length && (
              <div style={{ font: '500 11px/1.4 var(--font)', color: 'var(--text-4)' }}>
                …and {profile.other_jobs_count - profile.other_jobs.length} more.
              </div>
            )}
          </div>
        )}
      </div>

      {profile.unavailable_fields.length > 0 && (
        <div style={{ font: '500 11px/1.5 var(--font)', color: 'var(--text-4)' }}>
          {/* Named explicitly. "Not available" beats a blank that looks like a thin profile,
              and beats a fabricated headcount entirely. */}
          Not available for this employer: {profile.unavailable_fields.join(', ')}.
        </div>
      )}
    </div>
  );
}
