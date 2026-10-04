import Icon from '@/components/ui/Icon';
import type { AtsEvaluation, PaginationReport, TailoringAudit } from '@/types/resume';

/** The same summary renders in the app theme (Résumés page) and the Jobs drawer theme. */
export type SummaryVariant = 'app' | 'jc';

const TOKENS: Record<SummaryVariant, { text: string; text2: string; text3: string; border: string; surface: string }> = {
  app: { text: 'var(--text)', text2: 'var(--text-2)', text3: 'var(--text-3)', border: 'var(--border)', surface: 'var(--surface-2)' },
  jc: { text: 'var(--jc-text)', text2: 'var(--jc-text-2)', text3: 'var(--jc-text-3)', border: 'var(--jc-border)', surface: 'var(--jc-surface-2)' },
};

interface Props {
  audit: TailoringAudit;
  variant?: SummaryVariant;
}

/**
 * What a tailoring pass did, in plain terms: whether the PDF was edited, the ATS match before
 * and after (measured on the generated file, not on an intermediate string), what changed and
 * why, what was deliberately not added, and what the checks verified about the layout.
 *
 * Nothing here is optimistic: a pass that changed nothing says so, and an edit that could not
 * be placed is listed rather than hidden.
 */
export default function TailoringSummary({ audit, variant = 'app' }: Props) {
  const t = TOKENS[variant];
  const edited = audit.changes.length > 0;
  const delta = audit.final_ats_score - audit.original_ats_score;
  // `rejected_edits` already includes edits that would not fit the page (rule "layout"), so the
  // separate `skipped` list is not added again — that listed every layout skip twice.
  const notApplied = audit.rejected_edits
    .filter((r) => r.rule !== 'no_op')
    .map((r) => (r.rule === 'layout' || r.rule === 'pdf_check' ? `Not placed on the page: ${r.detail}` : `${r.rule.replace(/_/g, ' ')}: ${r.detail}`));
  const checks = audit.checks;

  return (
    <div data-testid="tailoring-summary" style={{ display: 'flex', flexDirection: 'column', gap: 12, color: t.text, fontFamily: 'var(--font)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 9px', borderRadius: 999,
            font: '700 11px/1 var(--font)',
            background: edited ? 'var(--offer-soft)' : t.surface,
            color: edited ? 'var(--offer)' : t.text2,
          }}
        >
          <Icon name={edited ? 'check' : 'alert'} size={12} />
          {edited ? `PDF edited in place · ${audit.changes.length} change${audit.changes.length === 1 ? '' : 's'}` : 'No changes made'}
        </span>
        <span style={{ font: '700 13px/1 var(--mono)' }} title="ATS match, scored on the generated PDF itself">
          ATS {audit.original_ats_score} → {audit.final_ats_score}
          {delta !== 0 && (
            <span style={{ marginLeft: 6, color: delta > 0 ? 'var(--offer)' : 'var(--rejected)' }}>
              {delta > 0 ? '+' : ''}{delta}
            </span>
          )}
        </span>
      </div>

      {audit.evaluation_after && (
        <MatchBreakdown
          before={audit.evaluation_before ?? null} after={audit.evaluation_after} note={audit.ats_target_note}
          reached={audit.ats_target_reached} target={audit.ats_target} color={t}
        />
      )}

      {audit.pagination && <PaginationRules report={audit.pagination} color={t} />}

      {!edited && (
        <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: t.text3 }}>
          Nothing in this résumé could be reworded for this posting without adding something your CV does not
          already show. The PDF is identical to the original — that is the honest result, not a failure.
        </p>
      )}

      {checks && (
        <div style={{ font: '500 11.5px/1.5 var(--font)', color: t.text3 }}>
          <span style={{ color: checks.ok ? 'var(--offer)' : 'var(--rejected)', fontWeight: 700 }}>
            {checks.ok ? 'Layout verified' : 'Layout check failed'}
          </span>
          {checks.ok && (
            <>
              {' '}· {checks.pages} page{checks.pages === 1 ? '' : 's'} · {checks.pixels_changed_outside_edits ?? 0} pixels
              changed outside the edited lines · fonts, margins and spacing untouched
            </>
          )}
        </div>
      )}

      {audit.changes.map((c) => (
        <div key={c.line_id} style={{ padding: 11, borderRadius: 10, background: t.surface, border: `1px solid ${t.border}` }}>
          <div style={{ font: '700 10px/1 var(--mono)', letterSpacing: '.05em', textTransform: 'uppercase', color: t.text3, marginBottom: 7 }}>
            {c.section || 'Summary'}
          </div>
          <div style={{ font: '500 12px/1.5 var(--font)', color: t.text3, textDecoration: 'line-through', marginBottom: 4 }}>{c.before_text}</div>
          {c.after_text ? (
            <div style={{ font: '600 12.5px/1.5 var(--font)', color: t.text }}>{c.after_text}</div>
          ) : (
            <div style={{ font: '700 11px/1.5 var(--mono)', letterSpacing: '.05em', textTransform: 'uppercase', color: t.text2 }}>
              Removed from this version
            </div>
          )}
          {c.reason && <div style={{ marginTop: 6, font: '500 11.5px/1.45 var(--font)', color: t.text2 }}>Why: {c.reason}</div>}
          {c.recovered_terms && c.recovered_terms.length > 0 ? (
            <div style={{ marginTop: 4, font: '500 11.5px/1.45 var(--font)', color: 'var(--review)' }}>
              Recovered from {(c.evidence_sources ?? []).join(', ')}: {c.recovered_terms.join(', ')}
            </div>
          ) : (
            <div style={{ marginTop: 4, font: '500 11px/1.45 var(--font)', color: t.text3 }}>Evidence: your current résumé</div>
          )}
          {c.keywords_added.length > 0 && (
            <div style={{ marginTop: 6, display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {c.keywords_added.map((k) => (
                <span key={k} style={{ padding: '2px 7px', borderRadius: 999, background: 'var(--offer-soft)', color: 'var(--offer)', font: '700 10.5px/1.3 var(--font)' }}>+ {k}</span>
              ))}
            </div>
          )}
        </div>
      ))}

      {audit.keywords_not_added.length > 0 && (
        <div>
          <div style={{ font: '700 11px/1 var(--font)', color: t.text2, marginBottom: 6 }}>
            Not added — your CV shows no evidence for these
          </div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {audit.keywords_not_added.map((k) => (
              <span key={k} style={{ padding: '2px 8px', borderRadius: 999, background: t.surface, border: `1px solid ${t.border}`, color: t.text3, font: '600 10.5px/1.3 var(--font)' }}>{k}</span>
            ))}
          </div>
        </div>
      )}

      {notApplied.length > 0 && (
        <details style={{ font: '500 11.5px/1.5 var(--font)', color: t.text3 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 700, color: t.text2 }}>
            {notApplied.length} proposed edit{notApplied.length === 1 ? '' : 's'} not applied
          </summary>
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {notApplied.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}


interface Tokens { text: string; text2: string; text3: string; border: string; surface: string }

const RULE_LABEL: Record<string, string> = {
  education_and_work_same_page: 'Education and Work on one page',
  extra_curricular_new_page: 'Extra-Curricular starts a new page',
  first_separator_on_page_one: 'First separator on page 1',
  no_orphans: 'No stranded headings or separators',
  no_blank_pages: 'No blank pages',
};

const TIER_LABEL: Record<string, string> = {
  critical: 'Critical', important: 'Important', supporting: 'Supporting', nice_to_have: 'Nice to have',
};

/** The honest breakdown behind the ATS number: parsing, shortlist readiness, what is evidenced and what is not. */
function MatchBreakdown({ before, after, note, reached, target, color: t }: {
  before: AtsEvaluation | null; after: AtsEvaluation; note?: string; reached?: boolean; target?: number; color: Tokens;
}) {
  const row = (label: string, b: number | undefined, a: number) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', font: '600 11.5px/1.6 var(--font)', color: t.text2 }}>
      <span>{label}</span>
      <span style={{ fontFamily: 'var(--mono)' }}>{b != null && b !== a ? `${b} → ` : ''}{a}</span>
    </div>
  );
  return (
    <div
      data-testid="match-breakdown"
      style={{ padding: 11, borderRadius: 10, background: t.surface, border: `1px solid ${t.border}`, display: 'flex', flexDirection: 'column', gap: 6 }}
    >
      <div style={{ font: '700 11px/1.4 var(--font)', color: t.text }}>
        {after.band} · shortlist readiness: {after.shortlist_band} · recruiter signal: {after.recruiter.signal}
      </div>
      {row('ATS match', before?.ats_match, after.ats_match)}
      {row('File parsing', before?.parsing, after.parsing)}
      {row('Shortlist readiness', before?.shortlist, after.shortlist)}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 2 }}>
        {Object.entries(after.tiers).filter(([, v]) => v.total > 0).map(([k, v]) => (
          <span
            key={k}
            title={`${v.matched} backed by real work, ${v.mentioned} only listed, ${v.total} in the posting`}
            style={{ padding: '2px 8px', borderRadius: 999, border: `1px solid ${t.border}`, color: t.text3, font: '600 10.5px/1.3 var(--font)' }}
          >
            {TIER_LABEL[k] ?? k} {v.matched}/{v.total}
          </span>
        ))}
      </div>
      {after.verdict.holding_back.length > 0 && (
        <div style={{ font: '500 11.5px/1.5 var(--font)', color: t.text3 }}>Holding it back: {after.verdict.holding_back.join(' ')}</div>
      )}
      {note && !reached && (
        <div style={{ font: '600 11.5px/1.5 var(--font)', color: 'var(--review)' }}>
          {target ? `Target ${target} not reached. ` : ''}{note}
        </div>
      )}
      {after.parsing_findings.length > 0 && (
        <div style={{ font: '500 11px/1.5 var(--font)', color: t.text3 }}>Parsing: {after.parsing_findings.join(' ')}</div>
      )}
    </div>
  );
}

/** Each hard pagination rule, with whether it holds in the delivered file and why not when it does not. */
function PaginationRules({ report, color: t }: { report: PaginationReport; color: Tokens }) {
  const final = report.after ?? report.before;
  if (!final) return null;
  const headline = {
    compliant: 'Page layout already met the rules',
    reflowed: 'Re-flowed to meet the page layout rules (no wording changed)',
    condensed: 'Shortened some bullets (words removed only) and re-flowed to meet the page layout rules',
    suppressed: 'Removed the bullets that add least to this job, then re-flowed to meet the page layout rules',
    not_met: 'Page layout rules not fully met',
    skipped: 'Page layout not checked',
    not_applied: 'Page layout unchanged (no edits were made)',
  }[report.status];
  return (
    <details data-testid="pagination-rules" style={{ font: '500 11.5px/1.5 var(--font)', color: t.text3 }}>
      <summary style={{ cursor: 'pointer', fontWeight: 700, color: final.ok ? 'var(--offer)' : 'var(--review)' }}>
        {headline} · {final.pages} page{final.pages === 1 ? '' : 's'}
      </summary>
      <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
        {final.rules.filter((r) => r.applicable).map((r) => (
          <li key={r.rule} style={{ color: r.ok ? t.text3 : 'var(--review)' }}>
            {r.ok ? '✓' : '✗'} {RULE_LABEL[r.rule] ?? r.rule}{r.ok ? '' : ` — ${r.detail}`}
          </li>
        ))}
      </ul>
      {report.status === 'not_met' && report.deficit_points != null && report.deficit_points > 0 && (
        <p style={{ margin: '6px 0 0' }}>
          Education and Work overflow one page by about {Math.round(report.deficit_points)}pt. Fitting them would mean
          removing content, which was not done.
        </p>
      )}
    </details>
  );
}
