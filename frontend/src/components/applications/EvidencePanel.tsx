import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import { atsPercent, relativeTime } from '@/lib/status';
import type { ApplicationEvidence, EvidenceLogEntry } from '@/types/evidence';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 16,
};

/** How a confirmation state reads to the operator, and how alarming it should look. */
const CONFIRMATION: Record<string, { label: string; tone: string; note: string }> = {
  confirmed: {
    label: 'Confirmed',
    tone: 'var(--applied)',
    note: 'The portal acknowledged the submission and the agent read the confirmation back.',
  },
  unconfirmed: {
    label: 'Not confirmed',
    tone: 'var(--pending)',
    note: 'The run finished without an error, but nothing corroborated that it was received.',
  },
  simulated: {
    label: 'Simulated',
    tone: 'var(--pending)',
    note: 'Live apply is off, so no browser ran and nothing was sent to the employer.',
  },
  failed: {
    label: 'Failed',
    tone: 'var(--rejected)',
    note: 'The attempt failed before anything could be confirmed.',
  },
  pending: {
    label: 'Not submitted yet',
    tone: 'var(--text-3)',
    note: 'Nothing has been sent for this application.',
  },
};

/**
 * The application evidence panel.
 *
 * The product says `Applied`. This answers the follow-up: applied where, to which job, using
 * which CV, through which account, at what time, with what result, and what the agent did.
 *
 * Two rules run through it. Every value is read from a record the backend actually wrote, and
 * anything never captured renders as "Not recorded" rather than as a blank — a convincing
 * empty field is worse than an admission, because it reads as fact. And every button here is
 * wired to something real: `Open job` uses the stored URL and is disabled with an explicit
 * reason when there isn't one.
 */
export default function EvidencePanel({
  evidence,
  isLoading,
  isError,
  errorStatus,
  errorDetail,
  onReload,
  onRetry,
  retrying,
  onOpenResume,
}: {
  evidence: ApplicationEvidence | undefined;
  isLoading: boolean;
  isError: boolean;
  /** HTTP status from the failed evidence request. 0 means the request never completed. */
  errorStatus?: number;
  errorDetail?: string;
  /** Refetch the evidence itself — distinct from `onRetry`, which re-queues the application. */
  onReload?: () => void;
  onRetry: () => void;
  retrying: boolean;
  onOpenResume: () => void;
}) {
  const [showAllLogs, setShowAllLogs] = useState(false);

  if (isLoading) {
    return (
      <div style={{ ...card, height: 320, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
    );
  }

  if (isError || !evidence) {
    // Three different failures used to render as one sentence claiming "this is a display
    // problem, not a missing record". That sentence was wrong in the case that actually
    // happened: the endpoint 404'd because the running server did not have the route, and
    // the panel confidently told the operator the data was fine. Say what went wrong, and
    // offer the retry, because a 404 and a dead network need different reactions.
    const status = errorStatus ?? 0;
    const [heading, body] =
      status === 404
        ? [
          'No evidence endpoint for this application',
          'The application id was not found, or the running API does not expose the evidence route. If the API was recently updated, it may need restarting.',
        ]
        : status === 0
          ? ['Could not reach the API', 'The request never completed. Check that the backend is running.']
          : status >= 500
            ? [`The API failed (HTTP ${status})`, 'The server errored while assembling this evidence. The stored history is unaffected.']
            : [`The evidence request was refused (HTTP ${status})`, errorDetail ?? 'No reason was returned.'];

    return (
      <div style={{ ...card, borderColor: 'var(--rejected)' }}>
        <div style={{ font: '700 13px/1.3 var(--font)', marginBottom: 6 }}>{heading}</div>
        <p style={{ margin: '0 0 12px', font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
          {body}
        </p>
        {onReload && (
          <button
            onClick={onReload}
            style={{
              height: 30, padding: '0 13px', borderRadius: 'var(--r-md)',
              background: 'var(--surface-2)', border: '1px solid var(--border)',
              color: 'var(--text-2)', font: '600 12px/1 var(--font)', cursor: 'pointer',
            }}
          >
            Try again
          </button>
        )}
      </div>
    );
  }

  // Loaded, but every section came back unrecorded. That is a real answer about an old
  // application, and it is not an error — saying "could not be loaded" here would send the
  // operator hunting for a fault that does not exist.
  if (
    !evidence.job.recorded &&
    !evidence.resume.recorded &&
    !evidence.account.recorded &&
    !evidence.log_recorded &&
    !evidence.submission.recorded
  ) {
    return (
      <div style={card}>
        <div style={{ font: '700 13px/1.3 var(--font)', marginBottom: 6 }}>
          Evidence not recorded for this application
        </div>
        <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
          It predates run recording, so no job snapshot, documents, account or log were kept.
          Applications created from now on record all four.
        </p>
      </div>
    );
  }

  const { job, submission, resume, cover_letter: letter, account, failure, log } = evidence;
  const confirmation = CONFIRMATION[submission.confirmation_state] ?? CONFIRMATION['pending']!;
  const shownLogs = showAllLogs ? log : log.slice(-6);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {failure && (
        <section style={{ ...card, borderColor: 'var(--rejected)' }}>
          <Heading icon="alert" tone="var(--rejected)">Failure</Heading>
          <p style={{ margin: '0 0 10px', font: '600 12.5px/1.5 var(--font)', color: 'var(--text)' }}>
            {failure.message}
          </p>
          {failure.root_cause && <Field label="Root cause" value={failure.root_cause} />}
          {failure.failure_class && <Field label="Class" value={failure.failure_class} />}
          {failure.failed_at && (
            <Field label="Failed" value={new Date(failure.failed_at).toLocaleString()} />
          )}
          {failure.url && <Field label="Where" value={failure.url} mono />}
          <Field
            label="Steps run"
            value={failure.step_count == null ? null : String(failure.step_count)}
          />
          {/* Only rendered when the backend says re-queueing is genuinely supported. */}
          {failure.can_retry && (
            <button
              onClick={onRetry}
              disabled={retrying}
              style={{
                marginTop: 10, height: 32, padding: '0 14px', borderRadius: 'var(--r-md)',
                background: 'var(--rejected-soft)', border: '1px solid var(--rejected)',
                color: 'var(--rejected)', font: '700 12px/1 var(--font)',
                cursor: retrying ? 'default' : 'pointer',
              }}
            >
              {retrying ? 'Re-queueing…' : 'Retry application'}
            </button>
          )}
        </section>
      )}

      <section style={card}>
        <Heading icon="briefcase">Job</Heading>
        {job.recorded ? (
          <>
            <div style={{ font: '700 13.5px/1.3 var(--font)', color: 'var(--text)' }}>
              {job.title ?? 'Untitled role'}
            </div>
            <div style={{ font: '500 12px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>
              {job.company ?? 'Unknown employer'}
              {job.location ? ` · ${job.location}` : ''}
            </div>
            <div style={{ marginTop: 10 }}>
              <Field label="Salary" value={job.salary} />
              <Field label="Source" value={job.source} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
              <LinkButton
                href={job.job_url}
                label="Open job"
                // Never fabricated. If no URL was stored, the button says so instead of
                // guessing one that would 404.
                missing="Job URL unavailable — none was stored with this application"
                primary
              />
              {job.application_url && (
                <LinkButton
                  href={job.application_url}
                  label="Open application"
                  missing=""
                />
              )}
            </div>
          </>
        ) : (
          <NotRecorded what="The job behind this application is no longer stored." />
        )}
      </section>

      <section style={card}>
        <Heading icon="check">Submission</Heading>
        <Field label="Status" value={submission.status.replace('_', ' ')} />
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '5px 0' }}>
          <span style={labelStyle}>Confirmation</span>
          <span style={{ font: '700 12px/1.4 var(--font)', color: confirmation.tone }}>
            {confirmation.label}
          </span>
        </div>
        <p style={{ margin: '2px 0 8px', font: '500 11.5px/1.45 var(--font)', color: 'var(--text-3)' }}>
          {confirmation.note}
        </p>
        <Field
          label="Submitted"
          value={submission.submitted_at ? new Date(submission.submitted_at).toLocaleString() : null}
        />
        <Field label="Method" value={submission.method} />
        <Field label="By" value={submission.actor} />
        <Field label="Mode" value={submission.apply_mode} />
        <Field label="Reference" value={submission.external_reference} mono />
        <Field
          label="ATS"
          value={submission.ats_score == null ? null : `${atsPercent(submission.ats_score)}%`}
        />
        {submission.confirmation_detail && (
          <p style={{ margin: '8px 0 0', font: '500 11.5px/1.45 var(--font)', color: 'var(--text-3)' }}>
            {/* The agent's own words, verbatim. A paraphrase of a confirmation is not one. */}
            {submission.confirmation_detail}
          </p>
        )}
      </section>

      <section style={card}>
        <Heading icon="file">Résumé used</Heading>
        {resume.recorded ? (
          <>
            <div style={{ font: '700 12.5px/1.3 var(--font)' }}>{resume.name}</div>
            <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>
              {resume.kind ? `${resume.kind} CV` : 'CV'}
              {resume.ats_score != null && ` · ${atsPercent(resume.ats_score)}% ATS`}
              {resume.created_at && ` · added ${relativeTime(resume.created_at)}`}
              {resume.archived && ' · archived, kept for this record'}
            </div>
            <button
              onClick={onOpenResume}
              style={{
                marginTop: 10, height: 30, padding: '0 12px', borderRadius: 'var(--r-md)',
                background: 'var(--surface-2)', border: '1px solid var(--border)',
                color: 'var(--text-2)', font: '600 11.5px/1 var(--font)', cursor: 'pointer',
              }}
            >
              View résumé
            </button>
          </>
        ) : (
          <NotRecorded what="No CV was attached to this application." />
        )}
      </section>

      <section style={card}>
        <Heading icon="mail">Cover letter</Heading>
        {letter.used ? (
          <>
            <div style={{ font: '700 12.5px/1.3 var(--font)' }}>{letter.name}</div>
            {letter.origin && (
              <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>
                {letter.origin === 'generated' ? 'Generated for this role' : letter.origin}
              </div>
            )}
          </>
        ) : (
          <div style={{ font: '500 12px/1.4 var(--font)', color: 'var(--text-3)' }}>
            No cover letter used.
          </div>
        )}
      </section>

      <section style={card}>
        <Heading icon="user">Account used</Heading>
        {account.recorded && account.platform ? (
          <>
            <div style={{ font: '700 12.5px/1.3 var(--font)' }}>{account.platform}</div>
            {/* Masked at rest and again on read. Never a password, cookie or token. */}
            <div style={{ font: '500 11.5px/1.4 var(--mono)', color: 'var(--text-3)', marginTop: 3 }}>
              {account.account ?? 'account not recorded'}
            </div>
            <div style={{
              font: '600 11.5px/1.4 var(--font)', marginTop: 5,
              color: account.connected ? 'var(--applied)' : 'var(--pending)',
            }}>
              {account.connected ? 'Connected' : (account.state ?? 'not connected').replace(/_/g, ' ')}
            </div>
            {account.detail && (
              <div style={{ font: '500 11.5px/1.45 var(--font)', color: 'var(--text-3)', marginTop: 4 }}>
                {account.detail}
              </div>
            )}
          </>
        ) : (
          <NotRecorded what="No account was recorded against this application." />
        )}
      </section>

      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Heading icon="activity">Run log</Heading>
          <span style={{ marginLeft: 'auto', font: '600 10px/1 var(--mono)', color: 'var(--text-4)' }}>
            {log.length} {log.length === 1 ? 'ENTRY' : 'ENTRIES'}
          </span>
        </div>
        {evidence.log_recorded ? (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 8 }}>
              {shownLogs.map((entry, i) => <LogRow key={i} entry={entry} />)}
            </div>
            {log.length > shownLogs.length && (
              <button
                onClick={() => setShowAllLogs(true)}
                style={{
                  marginTop: 10, height: 28, padding: '0 12px', borderRadius: 'var(--r-md)',
                  background: 'var(--surface-2)', border: '1px solid var(--border)',
                  color: 'var(--text-2)', font: '600 11.5px/1 var(--font)', cursor: 'pointer',
                }}
              >
                View full log ({log.length})
              </button>
            )}
          </>
        ) : (
          <NotRecorded what="No execution history was recorded for this application." />
        )}
      </section>
    </div>
  );
}

/* -- pieces ------------------------------------------------------------------------- */

const labelStyle: React.CSSProperties = {
  flex: '0 0 84px', font: '600 10px/1.5 var(--mono)', letterSpacing: '.08em',
  color: 'var(--text-4)', textTransform: 'uppercase',
};

function Heading({ icon, tone, children }: { icon: 'briefcase' | 'check' | 'file' | 'mail' | 'user' | 'activity' | 'alert'; tone?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 10, color: tone ?? 'var(--text-3)' }}>
      <Icon name={icon} size={13} />
      <span style={{ font: '700 10.5px/1 var(--mono)', letterSpacing: '.12em', textTransform: 'uppercase' }}>
        {children}
      </span>
    </div>
  );
}

/** One labelled value. A `null` renders as "Not recorded", never as an empty row. */
function Field({ label, value, mono }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '5px 0' }}>
      <span style={labelStyle}>{label}</span>
      <span
        style={{
          flex: '1 1 auto', minWidth: 0, wordBreak: 'break-word',
          font: value
            ? `600 12px/1.4 ${mono ? 'var(--mono)' : 'var(--font)'}`
            : '500 12px/1.4 var(--font)',
          color: value ? 'var(--text)' : 'var(--text-4)',
        }}
      >
        {value || 'Not recorded'}
      </span>
    </div>
  );
}

function NotRecorded({ what }: { what: string }) {
  return (
    <div style={{ font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>{what}</div>
  );
}

/**
 * A link to a real external page, or an explicit statement that there isn't one.
 *
 * Rendering a dead "Open job" button is the failure this avoids: it looks actionable, does
 * nothing, and leaves the operator unsure whether the URL is missing or the app is broken.
 */
function LinkButton({ href, label, missing, primary }: { href: string | null; label: string; missing: string; primary?: boolean }) {
  if (!href) {
    return (
      <div style={{ font: '500 11.5px/1.45 var(--font)', color: 'var(--text-4)' }}>
        {missing}
      </div>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 7,
        height: 34, padding: '0 14px', borderRadius: 'var(--r-md)', textDecoration: 'none',
        background: primary ? 'var(--accent)' : 'var(--surface-2)',
        border: `1px solid ${primary ? 'var(--accent)' : 'var(--border)'}`,
        color: primary ? 'var(--accent-ink)' : 'var(--text-2)',
        font: '700 12px/1 var(--font)',
      }}
    >
      {label} <Icon name="ext" size={13} />
    </a>
  );
}

function LogRow({ entry }: { entry: EvidenceLogEntry }) {
  const time = new Date(entry.at);
  const stamp = Number.isNaN(time.getTime())
    ? '--:--'
    : time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  return (
    <div style={{ display: 'flex', gap: 9, alignItems: 'baseline' }}>
      <span style={{ flex: '0 0 auto', font: '600 10.5px/1.5 var(--mono)', color: 'var(--text-4)' }}>
        {stamp}
      </span>
      <span
        title={entry.detail ?? undefined}
        style={{
          flex: '1 1 auto', minWidth: 0, font: '500 11.5px/1.5 var(--font)',
          // The agent's own steps are dimmer than lifecycle events: there are far more of
          // them, and the lifecycle is what the operator is usually scanning for.
          color: entry.source === 'automation' ? 'var(--text-3)' : 'var(--text-2)',
        }}
      >
        {entry.message}
      </span>
    </div>
  );
}
