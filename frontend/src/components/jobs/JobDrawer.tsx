import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';

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
import TailoringSummary from '@/components/resumes/TailoringSummary';
import { useGenerateResume, useResumePreviewUrl } from '@/hooks/useResumes';
import { apiErrorMessage } from '@/lib/apiError';
import { downloadResumeFile } from '@/services/resumeService';
import { useAppStore } from '@/store/useAppStore';
import { useFocusStore } from '@/store/useFocusStore';
import { jcSponsorMeta, jobStatusMeta } from '@/lib/status';
import { formatSalary, salaryBand } from '@/lib/jobModel';
import '@/styles/jobs-command.css';
import type { Job } from '@/types/job';
import type { Resume } from '@/types/resume';

type Tab = 'fit' | 'tailored' | 'posting' | 'company' | 'description';

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
  const navigate = useNavigate();
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
  const generate = useGenerateResume();
  const generating = useRef(false); // flips at once; `isPending` only on the next render

  // Tailoring always starts from a base CV. If a tailored variant is selected, its own base is
  // used, so the button never tries to tailor a document that was itself generated.
  const selectedResume = resumes.find((r) => r.id === resumeId);
  const baseResumeId = selectedResume
    ? selectedResume.type === 'base' ? selectedResume.id : selectedResume.base_resume_id
    : null;
  // The version for THIS job and base: the one just generated, or — after a refresh or when the
  // drawer is reopened — the one already stored. Both are the same record.
  const storedTailored = resumes.find(
    (r) => r.type === 'tailored' && r.job_id === job.id && r.base_resume_id === baseResumeId && r.has_pdf,
  );
  const justGenerated = generate.data && generate.data.job_id === job.id ? generate.data : undefined;
  const tailored = justGenerated ?? storedTailored ?? null;
  const preview = useResumePreviewUrl(tailored?.id ?? null, Boolean(tailored?.has_pdf));
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

  const runTailor = (regenerate: boolean) => {
    if (!baseResumeId) {
      notify('Choose the PDF CV to tailor first', 'warning');
      return;
    }
    if (generate.isPending || generating.current) return;
    generating.current = true;
    setTab('tailored');
    generate.mutate(
      { base_resume_id: baseResumeId, job_id: job.id, regenerate },
      {
        onSettled: () => { generating.current = false; },
        onSuccess: (r) =>
          r.tailoring_audit?.generation_status === 'unchanged'
            ? notify('No supportable changes — your PDF already covers this posting as far as your CV allows', 'info')
            : notify('Tailored résumé ready — PDF edited in place', 'success'),
        onError: (err) => notify(apiErrorMessage(err, 'Could not generate the tailored résumé'), 'error'),
      },
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
                  {/* The posting's own words, with the figure the list sorted and filtered on
                      beside them when the two differ. The card shows "£110k" for a posting
                      that reads "£500 per day"; without this the drawer contradicted it with
                      no explanation of where either number came from. */}
                  <span title={`As published: ${job.salary_range}`}>{job.salary_range}</span>
                  {(() => {
                    const band = salaryBand(job);
                    const normalised = formatSalary(band);
                    if (!normalised || !band.annualised) return null;
                    return (
                      <span style={{ color: 'var(--jc-text-4)' }}>
                        ({normalised} a year)
                      </span>
                    );
                  })()}
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
          <button
            onClick={() => (tailored ? setTab('tailored') : runTailor(false))}
            disabled={generate.isPending || !baseResumeId}
            title="Edit this PDF in place for this job — only the relevant wording changes, the layout is untouched"
            className="jc-btn jc-btn-secondary"
            style={{ flex: '0 0 auto', height: 34, padding: '0 14px' }}
          >
            <Icon name="wand" size={13} /> {generate.isPending ? 'Tailoring…' : tailored ? 'View tailored résumé' : 'Get tailored résumé'}
          </button>
        </div>

        {/* ---- Section switcher: Fit / Posting / Company / Description ------------------- */}
        <div style={{ flex: '0 0 auto', display: 'flex', gap: 5, padding: '14px 24px 0' }}>
          {([['fit', 'Fit'], ['tailored', tailored ? 'Tailored •' : 'Tailored'], ['posting', 'Posting'], ['company', 'Company'], ['description', 'Description']] as const).map(
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

          {tab === 'tailored' && (
            generate.isPending ? (
              <Centered>
                Tailoring your PDF… reading the posting, editing only the lines your CV can back up,
                then re-checking the file. This usually takes 10–60 seconds.
              </Centered>
            ) : generate.isError && !justGenerated ? (
              <Centered>
                <div style={{ color: 'var(--jc-text-2)', fontWeight: 700, marginBottom: 6 }}>Tailoring did not complete</div>
                <div style={{ marginBottom: 12 }}>{apiErrorMessage(generate.error, 'Something went wrong generating the PDF.')}</div>
                <button onClick={() => runTailor(false)} disabled={!baseResumeId} className="jc-btn jc-btn-primary" style={{ height: 34, padding: '0 14px' }}>
                  Try again
                </button>
              </Centered>
            ) : tailored ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <div className="jc-body" style={{ flex: '1 1 160px', minWidth: 0, fontWeight: 700 }}>{tailored.name}</div>
                  <button
                    onClick={() => downloadResumeFile(tailored.id, 'pdf', tailored.name).catch(() => notify('Could not download the PDF', 'error'))}
                    className="jc-btn jc-btn-primary" style={{ height: 32, padding: '0 12px' }}
                  >
                    <Icon name="download" size={13} /> Download PDF
                  </button>
                  <button onClick={() => runTailor(true)} disabled={generate.isPending} className="jc-btn jc-btn-secondary" style={{ height: 32, padding: '0 12px' }}>
                    <Icon name="refresh" size={13} /> Regenerate
                  </button>
                  <button onClick={() => navigate('/resumes')} className="jc-btn jc-btn-secondary" style={{ height: 32, padding: '0 12px' }}>
                    Open in Résumés
                  </button>
                </div>
                <div style={{ height: 360, borderRadius: 10, background: 'var(--jc-surface-2)', border: '1px solid var(--jc-border)', overflow: 'hidden', position: 'relative' }}>
                  {preview.url && (
                    <iframe
                      key={tailored.id}
                      src={`${preview.url}#toolbar=0&navpanes=0`}
                      title={`Preview of ${tailored.name}`}
                      style={{ width: '100%', height: '100%', border: 0, background: '#fff', display: 'block' }}
                    />
                  )}
                  {preview.loading && <Centered>Loading preview…</Centered>}
                  {preview.error && <Centered>Couldn&apos;t load the preview — the file is still downloadable.</Centered>}
                </div>
                {tailored.tailoring_audit && <TailoringSummary audit={tailored.tailoring_audit} variant="jc" />}
              </div>
            ) : (
              <Centered>
                {baseResumeId
                  ? 'Click "Get tailored résumé" to edit this PDF for this job. Only wording your CV can back up changes; the layout stays exactly as it is.'
                  : 'Choose a PDF CV above, then tailor it to this job.'}
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

          <button
            onClick={() => navigate(`/resume-intelligence?tailorJobId=${job.id}`)}
            className="jc-btn jc-btn-secondary"
            style={{ flex: '0 0 auto', height: 44 }}
            title="Analyse this job against a role résumé and propose evidence-grounded changes"
          >
            <Icon name="wand" size={14} /> Tailor résumé
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
