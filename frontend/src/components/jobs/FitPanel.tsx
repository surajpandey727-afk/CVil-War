import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import type { FitAnalysis, MatchLevel, RequirementMatch } from '@/types/fit';

/** How each match level reads and how much attention it should pull. */
const LEVEL: Record<MatchLevel, { label: string; tone: string; soft: string }> = {
  excellent: { label: 'Excellent', tone: 'var(--offer)', soft: 'var(--offer-soft)' },
  strong: { label: 'Strong', tone: 'var(--applied)', soft: 'var(--applied-soft)' },
  partial: { label: 'Partial', tone: 'var(--pending)', soft: 'var(--surface-3)' },
  weak: { label: 'Weak', tone: 'var(--pending)', soft: 'var(--surface-3)' },
  missing: { label: 'Missing', tone: 'var(--rejected)', soft: 'var(--rejected-soft)' },
};

const SOURCE_LABEL: Record<string, string> = {
  experience: 'Experience',
  skills: 'Skills',
  education: 'Education',
  summary: 'Summary',
  certifications: 'Certifications',
  projects: 'Projects',
  unattributed: 'CV',
};

const RECOMMENDATION_LABEL: Record<string, string> = {
  strengthen: 'Strengthen',
  quantify: 'Quantify',
  add_evidence: 'Add evidence',
  reword: 'Reword',
  cannot_evidence: 'Genuine gap',
};

const pct = (n: number) => `${Math.round(n * 100)}%`;

const scoreColour = (n: number) =>
  n >= 0.8 ? 'var(--offer)' : n >= 0.6 ? 'var(--applied)' : n >= 0.4 ? 'var(--pending)' : 'var(--rejected)';

/**
 * The compatibility report for one CV against one job.
 *
 * Three things it deliberately does not do, each because the alternative would mislead:
 *
 * A category the posting gave no basis for is not shown with a score — it appears under
 * "not assessed" with the reason. A "salary fit: 90%" against an advert with no published
 * band looks exactly like a measured number.
 *
 * Evidence is rendered as a quotation because the backend verified it appears verbatim in
 * the CV. Anything it could not verify arrived here as `missing` with the text stripped.
 *
 * A recommendation for something the CV cannot support is labelled a genuine gap, not
 * phrased as "add X" — the whole point is to never suggest claiming experience the operator
 * does not have.
 */
export default function FitPanel({ analysis }: { analysis: FitAnalysis }) {
  const [tab, setTab] = useState<'summary' | 'requirements' | 'advice'>('summary');

  const strong = analysis.matches.filter(
    (m) => m.level === 'strong' || m.level === 'excellent',
  );
  const gaps = analysis.matches.filter(
    (m) => m.level === 'missing' || m.level === 'weak' || m.level === 'partial',
  );

  return (
    <div>
      {analysis.stale_reason && (
        <Banner tone="var(--pending)">{analysis.stale_reason}</Banner>
      )}
      {analysis.method === 'keyword' && (
        // A degraded analysis must never be mistaken for a full one.
        <Banner tone="var(--pending)">
          Matched on keywords only — no language model was available, so equivalent wording
          may read as a gap. The result is weaker than a full analysis.
        </Banner>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
        <div style={{ flex: '0 0 auto', textAlign: 'center' }}>
          <div style={{ font: '800 30px/1 var(--mono)', color: scoreColour(analysis.overall) }}>
            {pct(analysis.overall)}
          </div>
          <div style={{ font: '600 9px/1 var(--mono)', letterSpacing: '.1em', color: 'var(--text-4)', marginTop: 4 }}>
            OVERALL
          </div>
        </div>
        <div style={{ flex: '1 1 auto', minWidth: 0, font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
          {analysis.resume_name} · {strong.length} strong {strong.length === 1 ? 'match' : 'matches'},{' '}
          {gaps.length} to address.
          {analysis.cached && analysis.analysed_at && (
            <> Assessed {new Date(analysis.analysed_at).toLocaleDateString()}.</>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 5, marginBottom: 12 }}>
        {([
          ['summary', 'Breakdown'],
          ['requirements', `Requirements (${analysis.matches.length})`],
          ['advice', `Advice (${analysis.recommendations.length})`],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            aria-pressed={tab === key}
            style={{
              height: 27, padding: '0 11px', borderRadius: 999, cursor: 'pointer',
              font: '600 11.5px/1 var(--font)',
              border: `1px solid ${tab === key ? 'var(--accent-line)' : 'var(--border)'}`,
              background: tab === key ? 'var(--accent-soft)' : 'var(--surface-2)',
              color: tab === key ? 'var(--accent)' : 'var(--text-3)',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'summary' && (
        <>
          {analysis.categories.map((category) => (
            <div key={category.key} style={{ marginBottom: 11 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
                <span style={{ font: '600 12px/1 var(--font)', color: 'var(--text-2)' }}>
                  {category.label}
                </span>
                <span style={{ marginLeft: 'auto', font: '700 12px/1 var(--mono)', color: scoreColour(category.score) }}>
                  {pct(category.score)}
                </span>
              </div>
              <div style={{ height: 5, borderRadius: 3, background: 'var(--surface-3)', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${category.score * 100}%`, background: scoreColour(category.score) }} />
              </div>
              {category.rationale && (
                <div style={{ font: '500 11px/1.45 var(--font)', color: 'var(--text-3)', marginTop: 4 }}>
                  {category.rationale}
                </div>
              )}
              {/* Data lineage: every number can say where it came from. */}
              {category.method && (
                <div style={{ font: '500 10.5px/1.4 var(--font)', color: 'var(--text-4)', marginTop: 2 }}>
                  {category.method}
                </div>
              )}
            </div>
          ))}

          {analysis.not_assessed.length > 0 && (
            <div style={{ marginTop: 14, padding: '10px 12px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
              <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.1em', color: 'var(--text-4)', textTransform: 'uppercase', marginBottom: 7 }}>
                Not assessed
              </div>
              {/* Stated rather than silently omitted: an absent category is information. */}
              {analysis.not_assessed.map((reason, i) => (
                <div key={i} style={{ font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
                  {reason}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === 'requirements' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
          {analysis.matches.length === 0 ? (
            <Empty>No requirements could be extracted from this posting.</Empty>
          ) : (
            analysis.matches.map((match, i) => <RequirementRow key={i} match={match} />)
          )}
        </div>
      )}

      {tab === 'advice' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {analysis.recommendations.length === 0 ? (
            <Empty>Nothing to change — this CV covers what the posting asks for.</Empty>
          ) : (
            analysis.recommendations.map((rec, i) => (
              <div key={i} style={{ padding: '10px 12px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                <span style={{
                  display: 'inline-block', marginBottom: 5, padding: '2px 6px', borderRadius: 4,
                  font: '700 9.5px/1.4 var(--mono)', letterSpacing: '.05em', textTransform: 'uppercase',
                  background: rec.kind === 'cannot_evidence' ? 'var(--rejected-soft)' : 'var(--surface-3)',
                  color: rec.kind === 'cannot_evidence' ? 'var(--rejected)' : 'var(--text-3)',
                }}>
                  {RECOMMENDATION_LABEL[rec.kind] ?? rec.kind}
                </span>
                <div style={{ font: '500 12px/1.5 var(--font)', color: 'var(--text-2)' }}>{rec.text}</div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function RequirementRow({ match }: { match: RequirementMatch }) {
  const meta = LEVEL[match.level];
  return (
    <div style={{ padding: '9px 11px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ flex: '1 1 auto', minWidth: 0, font: '600 12px/1.4 var(--font)', color: 'var(--text)' }}>
          {match.requirement}
        </span>
        <span style={{
          flex: '0 0 auto', padding: '2px 7px', borderRadius: 4, background: meta.soft,
          color: meta.tone, font: '700 9.5px/1.4 var(--mono)', letterSpacing: '.05em',
          textTransform: 'uppercase',
        }}>
          {meta.label}
        </span>
      </div>

      {match.required !== null && (
        <span style={{ font: '600 10px/1.4 var(--mono)', color: 'var(--text-4)' }}>
          {match.required ? 'REQUIRED' : 'PREFERRED'}
        </span>
      )}

      {match.evidence ? (
        <>
          {/* Safe to render as a quotation: the backend verified it appears verbatim in the
              CV, and anything unverifiable arrived as `missing` with the text stripped. */}
          <div style={{ font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)', marginTop: 5, fontStyle: 'italic' }}>
            “{match.evidence}”
          </div>
          <div style={{ font: '500 10.5px/1.4 var(--mono)', color: 'var(--text-4)', marginTop: 3 }}>
            CV → {SOURCE_LABEL[match.source ?? 'unattributed'] ?? 'CV'}
            {match.source_detail && ` → ${match.source_detail}`}
            {match.semantic && ' · matched on meaning'}
          </div>
        </>
      ) : (
        <div style={{ font: '500 11.5px/1.5 var(--font)', color: 'var(--text-4)', marginTop: 5 }}>
          Not evidenced in this CV.
        </div>
      )}
    </div>
  );
}

function Banner({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: 'flex', gap: 8, padding: '9px 11px', marginBottom: 12,
      borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: `1px solid ${tone}`,
      font: '500 11.5px/1.5 var(--font)', color: 'var(--text-2)',
    }}>
      <span style={{ flex: '0 0 auto', color: tone }}><Icon name="alert" size={14} /></span>
      <span style={{ minWidth: 0 }}>{children}</span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ font: '500 12px/1.5 var(--font)', color: 'var(--text-3)', padding: '8px 0' }}>
      {children}
    </div>
  );
}
