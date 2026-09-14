import { useEffect, useState, type ReactNode } from 'react';

import CompanyPanel from '@/components/jobs/CompanyPanel';
import PostingPanel from '@/components/jobs/PostingPanel';
import FitPanel from '@/components/jobs/FitPanel';
import Icon from '@/components/ui/Icon';
import {
  useAnalyseFit, useCompanyProfile, useEnrichJob, useResumeRecommendation, useStoredFit,
} from '@/hooks/useJobs';
import { useAppStore } from '@/store/useAppStore';
import { useFocusStore } from '@/store/useFocusStore';
import { sponsorMeta } from '@/lib/status';
import type { Job } from '@/types/job';
import type { Resume } from '@/types/resume';

const PLAT_COLOR: Record<string, string> = {
  linkedin: 'var(--approved)', indeed: 'var(--interview)',
  glassdoor: 'var(--applied)', exa: 'var(--accent)',
};

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
  const analyse = useAnalyseFit();
  const enrich = useEnrichJob();

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

  return (
    <>
      <div onClick={onClose} role="presentation" style={{ position: 'fixed', inset: 0, zIndex: 70, background: 'rgba(4,7,9,.5)', backdropFilter: 'blur(3px)', animation: 'aaPop .16s var(--ease)' }} />
      <aside
        role="dialog"
        aria-label="Job details"
        style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(96vw,620px)', zIndex: 71, background: 'var(--surface)', borderLeft: '1px solid var(--border-2)', boxShadow: 'var(--shadow-pop)', display: 'flex', flexDirection: 'column', fontFamily: 'var(--font)', color: 'var(--text)', animation: 'aaDrawer .28s var(--ease)' }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '20px 22px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ flex: '1 1 auto', minWidth: 0 }}>
            <div style={{ font: '800 18px/1.2 var(--font)', letterSpacing: '-.02em' }}>{job.title}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 8, font: '500 12.5px/1 var(--font)', color: 'var(--text-3)' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'var(--text-2)' }}>
                <Icon name="building" size={13} /> {job.company}
              </span>
              <span style={{ color: 'var(--text-4)' }}>·</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <Icon name="mappin" size={13} /> {job.location || (job.remote ? 'Remote' : '—')}
              </span>
              {job.salary_range && (
                <>
                  <span style={{ color: 'var(--text-4)' }}>·</span>
                  <span>{job.salary_range}</span>
                </>
              )}
            </div>
            <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 10 }}>
              <span style={{ padding: '3px 8px', borderRadius: 6, background: 'var(--surface-2)', border: '1px solid var(--border)', font: '600 10.5px/1 var(--mono)', color: PLAT_COLOR[job.platform] ?? 'var(--text-3)' }}>
                {job.platform}
              </span>
              {job.remote && <Tag>Remote</Tag>}
              {job.job_type && <Tag>{job.job_type}</Tag>}
              {(() => {
                const sm = sponsorMeta(job.sponsor_confidence);
                return (
                  <span
                    title={job.sponsor_evidence ?? undefined}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 8px', borderRadius: 6, background: sm.soft, color: sm.color, font: '700 11px/1 var(--font)' }}
                  >
                    <Icon name="shield" size={11} /> {sm.label}
                  </span>
                );
              })()}
              {/* The same destination as "Apply manually" at the foot of the drawer, repeated
                  here because that one sits below the fold — the operator's first question on
                  opening a job is often just "show me the actual posting". */}
              {applyUrl && (
                <a
                  href={applyUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => onApplyManually(applyUrl)}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 9px',
                    borderRadius: 6, background: 'var(--accent-soft)',
                    border: '1px solid var(--accent-line)', color: 'var(--accent)',
                    font: '600 10.5px/1.5 var(--font)', textDecoration: 'none',
                  }}
                >
                  Open posting <Icon name="ext" size={12} />
                </a>
              )}
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" style={{ flex: '0 0 auto', width: 32, height: 32, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-3)', cursor: 'pointer', display: 'grid', placeItems: 'center', font: '400 18px/1 var(--font)' }}>×</button>
        </div>

        {/* Résumé selection lives here, against this job — not on a separate screen. */}
        <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8, padding: '12px 22px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
          <label htmlFor="fit-resume" style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.1em', color: 'var(--text-4)', textTransform: 'uppercase' }}>
            CV
          </label>
          <select
            id="fit-resume"
            value={resumeId}
            onChange={(e) => setResumeId(e.target.value)}
            style={{ flex: '1 1 180px', minWidth: 0, height: 32, padding: '0 9px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)', color: 'var(--text)', font: '600 12px/1 var(--font)' }}
          >
            {resumes.length === 0 && <option value="">No CV uploaded yet</option>}
            {resumes.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
          <button
            onClick={() => runAnalysis(Boolean(analysis))}
            disabled={analyse.isPending || !resumeId}
            style={{
              flex: '0 0 auto', height: 32, padding: '0 14px', borderRadius: 'var(--r-md)',
              background: resumeId ? 'var(--accent)' : 'var(--surface-2)',
              border: `1px solid ${resumeId ? 'var(--accent)' : 'var(--border)'}`,
              color: resumeId ? 'var(--accent-ink)' : 'var(--text-4)',
              font: '700 12px/1 var(--font)',
              cursor: analyse.isPending || !resumeId ? 'default' : 'pointer',
            }}
          >
            {analyse.isPending ? 'Analysing…' : analysis ? 'Re-analyse' : 'Analyse my fit'}
          </button>
        </div>

        <div style={{ flex: '0 0 auto', display: 'flex', gap: 5, padding: '12px 22px 0' }}>
          {([['fit', 'Fit'], ['posting', 'Posting'], ['company', 'Company'], ['description', 'Description']] as const).map(
            ([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                aria-pressed={tab === key}
                style={{
                  height: 28, padding: '0 12px', borderRadius: 999, cursor: 'pointer',
                  font: '600 12px/1 var(--font)',
                  border: `1px solid ${tab === key ? 'var(--accent-line)' : 'var(--border)'}`,
                  background: tab === key ? 'var(--accent-soft)' : 'var(--surface-2)',
                  color: tab === key ? 'var(--accent)' : 'var(--text-3)',
                }}
              >
                {label}
              </button>
            ),
          )}
        </div>

        <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '16px 22px 20px' }}>
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
                  <p key={i} style={{ margin: 0, font: '500 12.5px/1.6 var(--font)', color: 'var(--text-2)' }}>{p}</p>
                ))}
              </div>
            ) : (
              // Real state, not an error: several boards publish no description on the
              // listing endpoint at all.
              <Centered>This source published no description for this role.</Centered>
            )
          )}
        </div>

        {/* The decision. Two routes, always distinguishable. */}
        <div style={{ flex: '0 0 auto', display: 'flex', gap: 9, padding: '14px 22px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
          <button
            onClick={() => onApplyWithAgent(resumeId || null)}
            disabled={applying}
            style={{ flex: '1 1 200px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, height: 42, borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 13px/1 var(--font)', cursor: applying ? 'default' : 'pointer' }}
          >
            <Icon name="cpu" size={14} /> {applying ? 'Queueing…' : 'Apply with agent'}
          </button>

          {applyUrl ? (
            <a
              href={applyUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => onApplyManually(applyUrl)}
              style={{ flex: '1 1 180px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, height: 42, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-2)', font: '700 13px/1 var(--font)', textDecoration: 'none' }}
            >
              Apply manually <Icon name="ext" size={14} />
            </a>
          ) : (
            <span style={{ flex: '1 1 180px', display: 'flex', alignItems: 'center', justifyContent: 'center', height: 42, font: '500 11.5px/1.4 var(--font)', color: 'var(--text-4)', textAlign: 'center' }}>
              No application URL was stored for this job
            </span>
          )}
        </div>
      </aside>
    </>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: '28px 8px', textAlign: 'center', color: 'var(--text-3)', font: '500 12.5px/1.6 var(--font)' }}>
      {children}
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return (
    <span style={{ padding: '3px 8px', borderRadius: 6, background: 'var(--surface-2)', border: '1px solid var(--border)', font: '600 11px/1 var(--font)', color: 'var(--text-3)' }}>
      {children}
    </span>
  );
}
