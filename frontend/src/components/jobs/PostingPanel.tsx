import { useMemo, useState } from 'react';

import Icon from '@/components/ui/Icon';
import type { Job } from '@/types/job';

/** Structured intelligence lifted from the posting, as the backend stores it. */
export interface PostingData {
  criteria?: Record<string, string>;
  requirements?: string[];
  benefits?: string[];
  years_required?: number | null;
  word_count?: number;
  requirement_count?: number;
  benefit_count?: number;
  source?: string;
}

const tile: React.CSSProperties = {
  flex: '1 1 118px', minWidth: 108, padding: '10px 12px', borderRadius: 'var(--r-md)',
  background: 'var(--surface-2)', border: '1px solid var(--border)',
};

/** One headline number with its label. */
function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div style={tile} title={hint}>
      <div style={{ font: '500 10px/1.2 var(--mono)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.06em' }}>
        {label}
      </div>
      <div style={{ font: '700 16px/1.25 var(--font)', color: 'var(--text)', marginTop: 4 }}>
        {value}
      </div>
      {hint && (
        <div style={{ font: '500 10.5px/1.35 var(--font)', color: 'var(--text-4)', marginTop: 2 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

/**
 * What the posting actually says.
 *
 * Every field here is the employer's own text. Requirement lines are lifted verbatim and the
 * criteria keep the labels LinkedIn published them under, because a record that paraphrases
 * the posting is a record you cannot check against the posting.
 *
 * The distinction this screen works hardest to preserve is between *absent* and *unfetched*.
 * A LinkedIn card carries no description at all, and the previous version reported that as
 * "0 requirements, salary not assessed" — indistinguishable from a posting that genuinely
 * lists neither. Until the full posting has been fetched, this says so and offers to fetch it.
 */
export default function PostingPanel({
  job,
  onEnrich,
  enriching,
}: {
  job: Job & { posting_data?: PostingData | null; enriched_at?: string | null };
  onEnrich: () => void;
  enriching: boolean;
}) {
  const data = job.posting_data ?? null;
  const [showAllReqs, setShowAllReqs] = useState(false);

  const requirements = useMemo(() => data?.requirements ?? [], [data]);
  const benefits = useMemo(() => data?.benefits ?? [], [data]);
  const criteria = useMemo(
    () => Object.entries(data?.criteria ?? {}).filter(([, v]) => v && v !== 'Not Applicable'),
    [data],
  );

  if (!job.enriched_at) {
    // Never fetched. Saying "no requirements" here would be a claim about the job that this
    // screen has no basis for.
    return (
      <div style={{ padding: '26px 4px', textAlign: 'center' }}>
        <div style={{ display: 'grid', placeItems: 'center', width: 40, height: 40, borderRadius: 11, background: 'var(--accent-soft)', color: 'var(--accent)', margin: '0 auto 10px' }}>
          <Icon name="search" size={18} />
        </div>
        <div style={{ font: '700 13px/1.3 var(--font)', marginBottom: 5 }}>
          The full posting hasn&rsquo;t been fetched yet
        </div>
        <p style={{ margin: '0 auto 14px', maxWidth: 340, font: '500 12px/1.55 var(--font)', color: 'var(--text-3)' }}>
          Search results carry only a title, company and location. Fetching the posting pulls
          its requirements, benefits and the employer&rsquo;s own criteria &mdash; which is also
          what the fit analysis reads.
        </p>
        <button onClick={onEnrich} disabled={enriching} style={primary(enriching)}>
          {enriching ? 'Fetching…' : 'Fetch the full posting'}
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
        <Tile
          label="Experience"
          value={data?.years_required ? `${data.years_required}+ yrs` : '—'}
          hint={data?.years_required ? 'Highest figure the posting states' : 'Not stated'}
        />
        <Tile label="Requirements" value={String(requirements.length)} hint="Lines asked for" />
        <Tile label="Benefits" value={String(benefits.length)} hint="Lines offered" />
        <Tile
          label="Length"
          value={data?.word_count ? `${data.word_count.toLocaleString()}w` : '—'}
          hint="Words in the posting"
        />
      </div>

      {criteria.length > 0 && (
        <section>
          <Heading>Employer&rsquo;s own criteria</Heading>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {criteria.map(([key, value]) => (
              <span key={key} style={{ padding: '5px 9px', borderRadius: 'var(--r-sm)', background: 'var(--surface-2)', border: '1px solid var(--border)', font: '500 11.5px/1.3 var(--font)', color: 'var(--text-2)' }}>
                <span style={{ color: 'var(--text-4)' }}>{key}: </span>
                {value}
              </span>
            ))}
          </div>
        </section>
      )}

      {requirements.length > 0 ? (
        <section>
          <Heading>
            What they ask for
            <span style={{ color: 'var(--text-4)', fontWeight: 500 }}> · verbatim</span>
          </Heading>
          <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 5 }}>
            {(showAllReqs ? requirements : requirements.slice(0, 8)).map((line, i) => (
              <li key={i} style={{ display: 'flex', gap: 8, font: '500 12px/1.55 var(--font)', color: 'var(--text-2)' }}>
                <span style={{ color: 'var(--accent)', flex: '0 0 auto' }}>&bull;</span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
          {requirements.length > 8 && (
            <button onClick={() => setShowAllReqs((v) => !v)} style={link}>
              {showAllReqs ? 'Show fewer' : `Show all ${requirements.length}`}
            </button>
          )}
        </section>
      ) : (
        <section>
          <Heading>What they ask for</Heading>
          <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
            The posting was fetched but sets out no separate requirements list. The full text is
            under Description.
          </p>
        </section>
      )}

      {benefits.length > 0 && (
        <section>
          <Heading>What they offer</Heading>
          <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 5 }}>
            {benefits.slice(0, 8).map((line, i) => (
              <li key={i} style={{ display: 'flex', gap: 8, font: '500 12px/1.55 var(--font)', color: 'var(--text-2)' }}>
                <span style={{ color: 'var(--applied)', flex: '0 0 auto' }}>&bull;</span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <button onClick={onEnrich} disabled={enriching} style={ghost}>
        {enriching ? 'Refetching…' : 'Refetch the posting'}
      </button>
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ font: '700 11px/1.2 var(--mono)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 8 }}>
      {children}
    </div>
  );
}

function primary(busy: boolean): React.CSSProperties {
  return {
    height: 32, padding: '0 15px', borderRadius: 'var(--r-md)', cursor: busy ? 'wait' : 'pointer',
    font: '600 12.5px/1 var(--font)', border: '1px solid var(--accent-line)',
    background: 'var(--accent-soft)', color: 'var(--accent)',
  };
}

const ghost: React.CSSProperties = {
  height: 28, padding: '0 12px', borderRadius: 'var(--r-md)', cursor: 'pointer',
  font: '600 11.5px/1 var(--font)', border: '1px solid var(--border)',
  background: 'var(--surface-2)', color: 'var(--text-3)', alignSelf: 'flex-start',
};

const link: React.CSSProperties = {
  marginTop: 7, padding: 0, border: 'none', background: 'none', cursor: 'pointer',
  font: '600 11.5px/1 var(--font)', color: 'var(--accent)',
};
