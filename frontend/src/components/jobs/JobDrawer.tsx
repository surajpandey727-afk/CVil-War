import { useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import CompanyLogo from '@/components/ui/CompanyLogo';
import CompanyPanel from '@/components/jobs/CompanyPanel';
import PostingPanel from '@/components/jobs/PostingPanel';
import FitPanel from '@/components/jobs/FitPanel';
import Icon from '@/components/ui/Icon';
import {
  useAnalyseFit, useCompanyProfile, useEnrichJob, useResumeRecommendation, useStoredFit,
  useUpdateJobStatus,
} from '@/hooks/useJobs';
import { useApplyReadiness } from '@/hooks/useApplications';
import { useAppStore } from '@/store/useAppStore';
import { useFocusStore } from '@/store/useFocusStore';
import { jcSponsorMeta, jobStatusMeta } from '@/lib/status';
import '@/styles/jobs-command.css';
import type { Job } from '@/types/job';
import type { Resume } from '@/types/resume';

type Tab = 'fit' | 'posting' | 'company' | 'description';

interface JobDrawerProps {
  job: Job;
  resumes: Resume[];
  onClose: () => void;
  /** Queue this job for the agent, using the CV chosen here. */
  onApplyWithAgent: (resumeId: string | null) => void;
  applying: boolean;
  /** Record that the operator is applying on the external site themselves. */
  onApplyManually: (url: string) => void;
  onOpenJobId: (jobId: string) => void;
}

/**
 * The job decision centre.
 *
 * The workflow is job-first by construction: opening a job establishes the context, and the
 * CV is chosen *here*, against this posting. The alternative — pick a CV somewhere else, then
 * go hunting for a job to compare it against — is the flow this replaces.
 *
 * Everything needed to answer "should I apply to this?" is in one place: the posting, the fit
 * assessment with its evidence and gaps, the employer, and the two ways to act. The two
 * actions are deliberately distinct and labelled: the agent applies for you, or you open the
 * real external page and apply yourself.
 */
export default function JobDrawer({
  job, resumes, onClose, onApplyWithAgent, applying, onApplyManually, onOpenJobId,
}: JobDrawerProps) {
  const notify = useAppStore((s) => s.showNotification);
  const setFocusedJob = useFocusStore((s) => s.setFocusedJob);
  const [tab, setTab] = useState<Tab>('fit');
  const [resumeId, setResumeId] = useState<string>('');

  // The floating ATS widget (mounted at the app shell) reads this to know which job's
  // recommendation to show, independent of whether this drawer stays open.
  useEffect(() => {
    setFocusedJob(job.id, job.title);
  }, [job.id, job.title, setFocusedJob]);

  const { data: recommendation } = useResumeRecommendation(job.id);

  // Default to whichever CV the recommendation engine ranks highest for this job; fall back
  // to the base CV (then any CV) only while that call hasn't returned yet. The operator can
  // always change it here.
  useEffect(() => {
    if (resumeId) return;
    const recommended = recommendation?.recommended_resume_id
      ? resumes.find((r) => r.id === recommendation.recommended_resume_id)
      : undefined;
    const fallback = resumes.find((r) => r.type === 'base') ?? resumes[0];
    const pick = recommended ?? fallback;
    if (pick) setResumeId(pick.id);
  }, [resumes, resumeId, recommendation]);

  const { data: stored } = useStoredFit(job.id, resumeId || undefined);
  const { data: company, isLoading: companyLoading } = useCompanyProfile(job.id);
  // The worker already refuses to apply without a session/CV/model — asking here means a
  // blocker surfaces with its fix *before* the click, not as a failed run afterward.
  const { data: readiness } = useApplyReadiness(job.id, resumeId || undefined);
  const blocked = readiness != null && !readiness.ready;
  const analyse = useAnalyseFit();
  const enrich = useEnrichJob();
  const updateStatus = useUpdateJobStatus();
  const isSaved = job.status === 'saved';

  const toggleSave = () =>
    updateStatus.mutate(
      { jobId: job.id, status: isSaved ? 'new' : 'saved' },
      {
        onSuccess: () => notify(isSaved ? 'Removed from saved' : 'Saved for later', 'success'),
        onError: () => notify('Could not update this job', 'error'),
      },
    );

  // The freshly computed result wins over the stored one for this render; both are the same
  // shape, so the panel does not care which it got.
  const analysis = analyse.data ?? stored ?? null;

  const runAnalysis = (refresh: boolean) => {
    if (!resumeId) {
      notify('Choose a CV to assess against this job', 'warning');
      return;
    }
    analyse.mutate(
      { jobId: job.id, resumeId, refresh },
      { onError: () => notify('Could not analyse this job', 'error') },
    );
  };

  const paras = (job.description || '').split(/\n\n+/).map((p) => p.trim()).filter(Boolean);
  // Never constructed. `application_url` is where the form is; `url` is the advert. Either
  // may be absent, and the buttons say so rather than pointing at a guess.
  const applyUrl = job.application_url || job.url || '';

  // Portalled to <body>: this drawer is mounted from JobSearchPage, which wraps its whole
  // tree in `animation: '... both'`. A `both` fill-mode keeps that ancestor "affected by"
  // its animated transform indefinitely (even once it settles at the identity transform),
  // which makes it a containing block for `position: fixed` descendants — this drawer was
  // positioning itself relative to that ~11,000px-tall content wrapper, not the viewport,
  // so it opened far off-screen instead of sliding in. Same root cause as the bulk-apply
  // selection bar on the same page.
  return createPortal(
    <>
      <div
        data-jc-theme=""
        onClick={onClose}
        role="presentation"
        className="jc-drawer-overlay"
        style={{ animation: 'jcPop .16s var(--jc-ease)' }}
      />
      <aside
        data-jc-theme=""
        role="dialog"
        aria-label="Job details"
        className="jc-drawer"
        style={{ fontFamily: 'var(--font)', animation: 'jcSlide .3s var(--jc-ease)' }}
      >
        {/* ---- Header: identity + status + close --------------------------------------- */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, padding: '22px 24px 18px', borderBottom: '1px solid var(--jc-border)' }}>
          <CompanyLogo name={job.company} />
          <div style={{ flex: '1 1 auto', minWidth: 0 }}>
            <div className="jc-display" style={{ fontSize: 19 }}>{job.title}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 7 }} className="jc-body">
              <span style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'var(--jc-text-2)', fontWeight: 700 }}>
                {job.company}
              </span>
              <span style={{ color: 'var(--jc-text-4)' }}>·</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <Icon name="mappin" size={12} /> {job.location || (job.remote ? 'Remote' : '—')}
              </span>
              {job.salary_range && (
                <>
                  <span style={{ color: 'var(--jc-text-4)' }}>·</span>
                  <span>{job.salary_range}</span>
                </>
              )}
            </div>
            <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 11, alignItems: 'center' }}>
              {(() => {
                const sm = jobStatusMeta(job.status);
                return (
                  <span className="jc-status" style={{ background: sm.soft, color: sm.color }}>
                    <span className="jc-status-dot" style={{ background: sm.color }} /> {sm.label}
                  </span>
                );
              })()}
              {job.remote && <Tag>Remote</Tag>}
              {job.job_type && <Tag>{job.job_type}</Tag>}
              {(() => {
                const sm = jcSponsorMeta(job.sponsor_confidence);
                return (
                  <span
                    title={job.sponsor_evidence ?? undefined}
                    className="jc-status"
                    style={{ background: sm.soft, color: sm.color }}
                  >
                    <Icon name="shield" size={11} /> {sm.label}
                  </span>
                );
              })()}
            </div>
          </div>
          <div style={{ flex: '0 0 auto', display: 'flex', gap: 8 }}>
            <button
              onClick={toggleSave}
              disabled={updateStatus.isPending}
              aria-pressed={isSaved}
              title={isSaved ? 'Remove from saved' : 'Save for later'}
              className="jc-btn jc-btn-secondary"
              style={{ width: 36, height: 36, padding: 0, borderRadius: 'var(--jc-r-sm)', color: isSaved ? 'var(--jc-accent-2)' : 'var(--jc-text-3)', borderColor: isSaved ? 'var(--jc-accent-line)' : 'var(--jc-border)' }}
            >
              <Icon name="bookmark" size={16} sw={isSaved ? 2.4 : 1.8} />
            </button>
            <button onClick={onClose} aria-label="Close" className="jc-btn jc-btn-secondary" style={{ width: 36, height: 36, padding: 0, borderRadius: 'var(--jc-r-sm)', fontSize: 18 }}>×</button>
          </div>
        </div>

        {applyUrl && (
          <div style={{ padding: '10px 24px', borderBottom: '1px solid var(--jc-border)' }}>
            <a
              href={applyUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => onApplyManually(applyUrl)}
              className="jc-meta"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--jc-accent-2)', textDecoration: 'none' }}
            >
              <Icon name="ext" size={12} /> View original posting
            </a>
          </div>
        )}

        {/* ---- Application Intelligence: CV chosen against THIS job ---------------------- */}
        <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8, padding: '14px 24px', borderBottom: '1px solid var(--jc-border)', flexWrap: 'wrap' }}>
          <label htmlFor="fit-resume" className="jc-micro">CV</label>
          <div className="jc-input" style={{ flex: '1 1 180px', height: 34 }}>
            <select
              id="fit-resume"
              value={resumeId}
              onChange={(e) => setResumeId(e.target.value)}
              style={{ flex: 1, minWidth: 0, background: 'transparent', border: 0, outline: 'none', color: 'var(--jc-text)', font: '600 12px/1 var(--font)' }}
            >
              {resumes.length === 0 && <option value="">No CV uploaded yet</option>}
              {resumes.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </div>
          <button
            onClick={() => runAnalysis(Boolean(analysis))}
            disabled={analyse.isPending || !resumeId}
            className={`jc-btn ${resumeId ? 'jc-btn-primary' : 'jc-btn-secondary'}`}
            style={{ flex: '0 0 auto', height: 34, padding: '0 14px' }}
          >
            {analyse.isPending ? 'Analysing…' : analysis ? 'Re-analyse' : 'Analyse my fit'}
          </button>
        </div>

        {/* ---- Section switcher: Fit / Posting / Company / Description ------------------- */}
        <div style={{ flex: '0 0 auto', display: 'flex', gap: 5, padding: '14px 24px 0' }}>
          {([['fit', 'Fit'], ['posting', 'Posting'], ['company', 'Company'], ['description', 'Description']] as const).map(
            ([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                aria-pressed={tab === key}
                data-on={tab === key}
                className="jc-drawer-tab"
              >
                {label}
              </button>
            ),
          )}
        </div>

        <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '18px 24px 22px' }}>
          {tab === 'fit' && (
            analyse.isPending ? (
              <Centered>Reading the posting and your CV…</Centered>
            ) : analysis ? (
              <FitPanel analysis={analysis} />
            ) : (
              <Centered>
                {resumes.length === 0
                  ? 'Upload a CV first, then assess it against this job.'
                  : 'Choose a CV above and analyse your fit against this job.'}
              </Centered>
            )
          )}

          {tab === 'posting' && (
            <PostingPanel
              job={job}
              enriching={enrich.isPending}
              onEnrich={() => enrich.mutate({ jobId: job.id, force: Boolean(job.enriched_at) })}
            />
          )}

          {tab === 'company' && (
            companyLoading ? (
              <Centered>Loading what is known about {job.company}…</Centered>
            ) : company ? (
              <CompanyPanel profile={company} onOpenJob={onOpenJobId} />
            ) : (
              <Centered>Company information could not be loaded.</Centered>
            )
          )}

          {tab === 'description' && (
            paras.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                {paras.map((p, i) => (
                  <p key={i} className="jc-body" style={{ margin: 0, lineHeight: 1.6 }}>{p}</p>
                ))}
              </div>
            ) : (
              // Real state, not an error: several boards publish no description on the
              // listing endpoint at all.
              <Centered>This source published no description for this role.</Centered>
            )
          )}
        </div>

        {/* ---- Actions: two distinguishable routes, plus save --------------------------- */}
        {blocked && (
          <div style={{ flex: '0 0 auto', margin: '0 24px', padding: '10px 12px', borderRadius: 'var(--r-md)', background: 'var(--jc-surface-3)', border: '1px solid var(--jc-border)' }}>
            <div style={{ font: '700 11.5px/1.3 var(--font)', color: 'var(--jc-text-2)', marginBottom: 4 }}>
              The agent can't apply here yet
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {readiness!.blockers.map((b) => (
                <div key={b.code} style={{ font: '500 11px/1.4 var(--font)', color: 'var(--jc-text-3)' }}>
                  · {b.message} — <span style={{ color: 'var(--jc-text-2)' }}>{b.action}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div style={{ flex: '0 0 auto', display: 'flex', gap: 9, padding: '16px 24px', borderTop: '1px solid var(--jc-border)', flexWrap: 'wrap' }}>
          <button
            onClick={() => onApplyWithAgent(resumeId || null)}
            disabled={applying || blocked}
            title={blocked ? 'Resolve the blockers above first' : undefined}
            className="jc-btn jc-btn-primary"
            style={{ flex: '1 1 200px', height: 44 }}
          >
            <Icon name="cpu" size={14} /> {applying ? 'Queueing…' : 'Apply with agent'}
          </button>

          {applyUrl ? (
            <a
              href={applyUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => onApplyManually(applyUrl)}
              className="jc-btn jc-btn-secondary"
              style={{ flex: '1 1 180px', height: 44, textDecoration: 'none' }}
            >
              Apply manually <Icon name="ext" size={14} />
            </a>
          ) : (
            <span style={{ flex: '1 1 180px', display: 'flex', alignItems: 'center', justifyContent: 'center', height: 44, font: '500 11.5px/1.4 var(--font)', color: 'var(--jc-text-4)', textAlign: 'center' }}>
              No application URL was stored for this job
            </span>
          )}
        </div>
      </aside>
    </>,
    document.body,
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: '28px 8px', textAlign: 'center', color: 'var(--jc-text-3)', font: '500 12.5px/1.6 var(--font)' }}>
      {children}
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return (
    <span style={{ padding: '3px 8px', borderRadius: 6, background: 'var(--jc-surface-2)', border: '1px solid var(--jc-border)', font: '600 11px/1 var(--font)', color: 'var(--jc-text-3)' }}>
      {children}
    </span>
  );
}
