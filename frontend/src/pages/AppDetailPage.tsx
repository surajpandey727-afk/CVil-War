import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import EvidencePanel from '@/components/applications/EvidencePanel';
import FillActivityPanel from '@/components/applications/FillActivityPanel';
import RunTimeline from '@/components/applications/RunTimeline';
import {
  useApplication,
  useApplicationEvidence,
  useGenerateCoverLetter,
  useUpdateApplicationStatus,
} from '@/hooks/useApplications';
import { useLogRecruiterContact } from '@/hooks/useCommunications';
import { useResumes } from '@/hooks/useResumes';
import { useAppStore } from '@/store/useAppStore';
import { buildAppTimeline } from '@/lib/timeline';
import { statusMeta, atsColor, atsPercent, relativeTime } from '@/lib/status';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};
const ACTIVE = new Set(['queued', 'pending_review', 'approved', 'applying']);

export default function AppDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const notify = useAppStore((s) => s.showNotification);
  const { data: app, isLoading, isError } = useApplication(id);
  const {
    data: evidence, isLoading: evidenceLoading, isError: evidenceError,
    error: evidenceErr, refetch: reloadEvidence,
  } = useApplicationEvidence(id);
  const updateStatus = useUpdateApplicationStatus();
  const generateCoverLetter = useGenerateCoverLetter();
  const logRecruiterContact = useLogRecruiterContact();
  const { data: resumeData } = useResumes();
  const resumes = resumeData?.items ?? [];
  const [pickedResumeId, setPickedResumeId] = useState('');
  const [contactOpen, setContactOpen] = useState(false);
  const [contact, setContact] = useState({ email: '', first_name: '', last_name: '', title: '' });

  const setStatus = (status: string, msg: string) =>
    app &&
    updateStatus.mutate(
      { appId: app.id, update: { status } },
      { onSuccess: () => notify(msg, 'success'), onError: () => notify('Could not update status', 'error') },
    );

  const attachResume = () =>
    app &&
    pickedResumeId &&
    updateStatus.mutate(
      { appId: app.id, update: { status: app.status, resume_id: pickedResumeId } },
      {
        onSuccess: () => notify('Résumé attached', 'success'),
        onError: () => notify('Could not attach that résumé', 'error'),
      },
    );

  const generateLetter = () =>
    app &&
    generateCoverLetter.mutate(app.id, {
      onSuccess: () => {
        void reloadEvidence();
        notify(app.has_cover_letter ? 'Cover letter regenerated' : 'Cover letter generated', 'success');
      },
      onError: () => notify('Could not generate a cover letter', 'error'),
    });

  const submitContact = () =>
    app &&
    contact.email &&
    logRecruiterContact.mutate(
      { applicationId: app.id, ...contact },
      {
        onSuccess: (result) => {
          void reloadEvidence();
          setContactOpen(false);
          setContact({ email: '', first_name: '', last_name: '', title: '' });
          notify(
            result.matched_existing ? 'Contact updated in Apollo and logged to the timeline' : 'Contact logged to Apollo and the timeline',
            'success',
          );
        },
        onError: () => notify('Could not log that contact', 'error'),
      },
    );

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1180 }}>
      <button
        onClick={() => navigate('/applications')}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 30, padding: '0 10px 0 8px', marginBottom: 16, borderRadius: 'var(--r-md)', background: 'transparent', border: '1px solid transparent', color: 'var(--text-3)', font: '600 12.5px/1 var(--font)', cursor: 'pointer' }}
      >
        <Icon name="chevL" size={15} /> Applications
      </button>

      {isLoading ? (
        <div style={{ ...card, height: 160, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />
      ) : isError || !app ? (
        <div style={{ ...card, padding: '40px 20px', textAlign: 'center', color: 'var(--text-3)' }}>
          <div style={{ display: 'inline-grid', placeItems: 'center', width: 44, height: 44, borderRadius: 12, background: 'var(--failed-soft)', color: 'var(--failed)', marginBottom: 12 }}>
            <Icon name="alert" size={20} />
          </div>
          <div style={{ font: '700 15px/1.2 var(--font)', color: 'var(--text)' }}>Application not found</div>
          <p style={{ margin: '6px 0 0', font: '500 12.5px/1.4 var(--font)' }}>It may have been removed, or the link is stale.</p>
        </div>
      ) : (
        (() => {
          const sm = statusMeta(app.status);
          const realDiagnosis = evidence?.failure?.root_cause ?? evidence?.failure?.message ?? undefined;
          const steps = buildAppTimeline(app.apply_mode, app.status, realDiagnosis);
          return (
            <>
              {/* Header */}
              <div style={{ ...card, padding: 20, marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      <h1 style={{ margin: 0, font: '800 21px/1.2 var(--font)', letterSpacing: '-.02em' }}>{app.job_title ?? 'Untitled role'}</h1>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 24, padding: '0 10px', borderRadius: 999, background: sm.soft, color: sm.color, font: '700 11.5px/1 var(--font)' }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: sm.color }} />
                        {sm.label}
                      </span>
                    </div>
                    <p style={{ margin: '7px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
                      {app.company ?? '—'} · {app.apply_mode} mode · {app.applied_at ? `applied ${relativeTime(app.applied_at)}` : `created ${relativeTime(app.created_at)}`}
                    </p>
                  </div>
                  {app.ats_score != null && (
                    <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
                      <span style={{ font: '800 24px/1 var(--mono)', color: atsColor(atsPercent(app.ats_score)) }}>{atsPercent(app.ats_score)}</span>
                      <span style={{ font: '600 9px/1 var(--mono)', letterSpacing: '.1em', color: 'var(--text-4)' }}>ATS</span>
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', gap: 9, marginTop: 16, flexWrap: 'wrap' }}>
                  {app.status === 'failed' && (
                    <ActionButton icon="refresh" label="Re-run" primary disabled={updateStatus.isPending} onClick={() => setStatus('queued', 'Re-queued — the agent will retry')} />
                  )}
                  <ActionButton
                    icon="file"
                    label={generateCoverLetter.isPending ? 'Generating…' : app.has_cover_letter ? 'Regenerate cover letter' : 'Generate cover letter'}
                    disabled={generateCoverLetter.isPending}
                    onClick={generateLetter}
                  />
                  <ActionButton
                    icon="mail"
                    label="Log recruiter contact"
                    disabled={logRecruiterContact.isPending}
                    onClick={() => setContactOpen((o) => !o)}
                  />
                  {ACTIVE.has(app.status) && (
                    <ActionButton icon="x" label="Withdraw" danger disabled={updateStatus.isPending} onClick={() => setStatus('withdrawn', 'Application withdrawn')} />
                  )}
                  {/* "View job" used to bounce to the jobs list, which is not the job. The
                      evidence panel's "Open job" opens the actual stored URL, so the
                      misleading duplicate is gone rather than sitting next to the real one. */}
                </div>

                {contactOpen && (
                  <div style={{ marginTop: 14, padding: 14, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                    <div style={{ font: '700 12.5px/1 var(--font)', marginBottom: 10 }}>Log a recruiter contact</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8 }}>
                      <input
                        type="email"
                        placeholder="Email *"
                        aria-label="Recruiter email"
                        value={contact.email}
                        onChange={(e) => setContact({ ...contact, email: e.target.value })}
                        style={inputStyle}
                      />
                      <input
                        type="text"
                        placeholder="First name"
                        aria-label="Recruiter first name"
                        value={contact.first_name}
                        onChange={(e) => setContact({ ...contact, first_name: e.target.value })}
                        style={inputStyle}
                      />
                      <input
                        type="text"
                        placeholder="Last name"
                        aria-label="Recruiter last name"
                        value={contact.last_name}
                        onChange={(e) => setContact({ ...contact, last_name: e.target.value })}
                        style={inputStyle}
                      />
                      <input
                        type="text"
                        placeholder="Title"
                        aria-label="Recruiter title"
                        value={contact.title}
                        onChange={(e) => setContact({ ...contact, title: e.target.value })}
                        style={inputStyle}
                      />
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      <ActionButton
                        icon="mail"
                        label={logRecruiterContact.isPending ? 'Logging…' : 'Log contact'}
                        primary
                        disabled={!contact.email || logRecruiterContact.isPending}
                        onClick={submitContact}
                      />
                      <ActionButton icon="x" label="Cancel" onClick={() => setContactOpen(false)} />
                    </div>
                  </div>
                )}
              </div>

              {/* The dashboard's "CV required" action lands here — this used to route to
                  the generic /resumes page with no way to attach a choice back to this
                  specific application, because there was nothing here to attach it with. */}
              {(!app.resume_id || app.resume_archived) && (
                <div style={{ ...card, padding: 18, marginBottom: 16, borderColor: 'var(--review)' }}>
                  <div style={{ font: '700 13px/1 var(--font)', marginBottom: 4 }}>
                    {app.resume_archived ? 'The résumé used here has since been archived' : 'No résumé selected'}
                  </div>
                  <p style={{ margin: '0 0 12px', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
                    Choose one before this application can be submitted.
                  </p>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <select
                      aria-label="Choose a résumé"
                      value={pickedResumeId}
                      onChange={(e) => setPickedResumeId(e.target.value)}
                      style={{ height: 34, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)', font: '600 12.5px/1 var(--font)', minWidth: 220 }}
                    >
                      <option value="">Select a résumé…</option>
                      {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                    <ActionButton
                      icon="briefcase"
                      label={updateStatus.isPending ? 'Attaching…' : 'Attach résumé'}
                      primary
                      disabled={!pickedResumeId || updateStatus.isPending}
                      onClick={attachResume}
                    />
                  </div>
                </div>
              )}

              {/* Timeline on the left, evidence on the right. The right-hand column was
                  empty space; it is now where "Applied — prove it" is answered. */}
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,360px)', gap: 16, alignItems: 'start' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
                  <div style={{ ...card, padding: 20 }}>
                    <div style={{ font: '700 14px/1 var(--font)', letterSpacing: '-.01em', marginBottom: 16 }}>Run timeline</div>
                    <RunTimeline steps={steps} />
                  </div>

                  <FillActivityPanel applicationId={app.id} isApplying={app.status === 'applying'} />

                  {app.notes && (
                    <div style={{ ...card, padding: 18 }}>
                      <div style={{ font: '700 13px/1 var(--font)', marginBottom: 8 }}>Notes</div>
                      <p style={{ margin: 0, font: '500 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>{app.notes}</p>
                    </div>
                  )}
                </div>

                <div style={{ minWidth: 0 }}>
                  <EvidencePanel
                    evidence={evidence}
                    isLoading={evidenceLoading}
                    isError={evidenceError}
                    // The API client normalises every failure to { detail, status_code }, so
                    // the panel can tell a 404 from a dead backend instead of guessing.
                    errorStatus={(evidenceErr as { status_code?: number } | null)?.status_code}
                    errorDetail={(evidenceErr as { detail?: string } | null)?.detail}
                    onReload={() => void reloadEvidence()}
                    retrying={updateStatus.isPending}
                    onRetry={() => setStatus('queued', 'Re-queued — the agent will retry')}
                    onOpenResume={() => navigate('/resumes')}
                  />
                </div>
              </div>
            </>
          );
        })()
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  height: 32, padding: '0 10px', borderRadius: 'var(--r-sm)', background: 'var(--surface-3)',
  border: '1px solid var(--border)', color: 'var(--text)', font: '500 12px/1 var(--font)', outline: 'none',
};

function ActionButton({ icon, label, onClick, primary, danger, disabled }: { icon: 'refresh' | 'x' | 'briefcase' | 'file' | 'mail'; label: string; onClick: () => void; primary?: boolean; danger?: boolean; disabled?: boolean }) {
  const bg = primary ? 'var(--accent)' : danger ? 'var(--rejected-soft)' : 'var(--surface-2)';
  const color = primary ? 'var(--accent-ink)' : danger ? 'var(--rejected)' : 'var(--text-2)';
  const border = primary ? 'var(--accent)' : danger ? 'var(--rejected)' : 'var(--border)';
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 34, padding: '0 13px', borderRadius: 'var(--r-md)', background: bg, border: `1px solid ${border}`, color, font: '700 12px/1 var(--font)', cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.6 : 1 }}
    >
      <Icon name={icon} size={14} sw={2} /> {label}
    </button>
  );
}
