/** Résumé checker — one résumé against one job, or against the Skill Radar role set.
 *
 *  Two layers, deliberately decoupled. The deterministic check is fast and returns the whole
 *  report: a fit score that shows its arithmetic, quoted evidence, ranked gaps, ATS coverage,
 *  section findings and rule-based rewrites. The AI review is fired as soon as the check lands
 *  and merges in when it finishes (section notes, extra suggestions); it never blocks the
 *  report, and when it is unavailable the check stands on its own.
 */
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import CheckBrief, { type TargetMode } from '@/components/resumeCheck/CheckBrief';
import FitScorecard from '@/components/resumeCheck/FitScorecard';
import ReviewStatus from '@/components/resumeCheck/ReviewStatus';
import ReportSection from '@/components/resumeCheck/ReportSection';
import { MatchedSkills, MissingSkills } from '@/components/resumeCheck/SkillsReport';
import AtsCoverage from '@/components/resumeCheck/AtsCoverage';
import SectionReviewList from '@/components/resumeCheck/SectionReviewList';
import SuggestionList from '@/components/resumeCheck/SuggestionList';
import { BAND } from '@/components/resumeCheck/reportMeta';
import { useResumeCheck, useResumeReview } from '@/hooks/useResumeCheck';
import { useResumes } from '@/hooks/useResumes';
import { useSkillRoles } from '@/hooks/useSkills';
import { apiErrorMessage } from '@/lib/apiError';
import { atsPercent } from '@/lib/status';
import type { ResumeCheckRequest } from '@/types/resumeCheck';
import '@/styles/resume-check.css';

/** The same seed as Skill Radar, so "Skill Radar roles" means the same set on arrival. */
const DEFAULT_ROLES = ['AI Product Manager', 'Product Manager', 'Product Analyst', 'Technical Product Manager'];

export default function ResumeCheckerPage() {
  const [params] = useSearchParams();
  const { data: resumeData, isLoading: resumesLoading, isError: resumesError } = useResumes();
  const { data: roleList } = useSkillRoles();
  const check = useResumeCheck();
  const review = useResumeReview();

  // ?resume=<id> (from the Résumés page) and ?job=<id> preselect the brief.
  const [resumeId, setResumeId] = useState(() => params.get('resume') ?? '');
  const [jobId, setJobId] = useState(() => params.get('job') ?? '');
  const [mode, setMode] = useState<TargetMode>('job');
  const [roles, setRoles] = useState<string[]>(DEFAULT_ROLES);

  const resumes = useMemo(() => (resumeData?.items ?? []).filter((r) => !r.archived), [resumeData]);
  const result = check.data;
  const reviewData = review.data;
  const aiReady = reviewData?.available === true;

  const suggestions = useMemo(
    () => [...(result?.suggestions ?? []), ...(aiReady ? reviewData.suggestions : [])],
    [result, aiReady, reviewData],
  );

  const run = () => {
    if (!resumeId) return;
    // Exactly one target goes over the wire; the other key is left out entirely.
    const body: ResumeCheckRequest = mode === 'job'
      ? { resume_id: resumeId, job_id: jobId || null }
      : { resume_id: resumeId, role_titles: roles };
    review.reset();
    check.mutate(body, { onSuccess: () => review.mutate(body) });
  };

  const toggleRole = (t: string) =>
    setRoles((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));

  const scanned = result?.corpus.uk_jobs_scanned ?? 0;

  return (
    <div className="rc">
      <header className="rc-head">
        <h1>Résumé checker</h1>
        <p>
          Check a résumé against one job or your Skill Radar roles. You get a fit score with its
          working shown, the lines that prove each skill, what&apos;s missing ranked by UK demand,
          and rewrites you can copy.
        </p>
      </header>

      <CheckBrief
        resumes={resumes} resumesLoading={resumesLoading} resumesError={resumesError}
        resumeId={resumeId} onResume={setResumeId}
        mode={mode} onMode={setMode}
        jobId={jobId} onJob={setJobId}
        roles={roleList ?? DEFAULT_ROLES} selectedRoles={roles} onToggleRole={toggleRole} onSetRoles={setRoles}
        onRun={run} running={check.isPending}
        error={check.isError ? apiErrorMessage(check.error, 'Could not check this résumé') : null}
      />

      {/* One polite announcement per finished check; the AI panel announces itself. */}
      <div className="rc-sr" aria-live="polite">
        {result ? `Check complete: ${atsPercent(result.score.overall)} out of 100, ${BAND[result.score.band].label}.` : ''}
      </div>

      {check.isPending ? (
        <div className="rc-panel" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span className="rc-spin" aria-hidden="true" />
          <span className="rc-hint">Checking the résumé…</span>
        </div>
      ) : !result ? (
        !check.isError && (
          <div className="rc-panel" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <span style={{ color: 'var(--text-2)' }}><Icon name="file" size={18} /></span>
            <p className="rc-hint">Choose a résumé and a target, then run the check. The report appears here.</p>
          </div>
        )
      ) : (
        <div className="rc-report">
          <aside className="rc-aside" aria-label="Score and AI review">
            <FitScorecard score={result.score} target={result.target} resumeName={result.resume_name} />
            <ReviewStatus pending={review.isPending} error={review.isError ? review.error : null} review={reviewData} />
          </aside>

          <article className="rc-panel rc-doc" aria-label="Résumé check report">
            <ReportSection id="rc-matched" n={1} title="Skills the résumé proves" meta={`${result.matched_skills.length} matched`}>
              <MatchedSkills skills={result.matched_skills} />
            </ReportSection>
            <ReportSection
              id="rc-missing" n={2} title="What's missing"
              meta={scanned > 0 ? `ranked by demand across ${scanned} UK jobs` : 'demand ranking needs a UK job corpus'}
            >
              <MissingSkills skills={result.missing_skills} scanned={scanned} />
            </ReportSection>
            <ReportSection id="rc-ats" n={3} title="ATS keyword coverage">
              <AtsCoverage ats={result.ats_keywords} />
            </ReportSection>
            <ReportSection id="rc-sections" n={4} title="Section by section" meta={review.isPending ? 'AI notes pending…' : undefined}>
              <SectionReviewList sections={result.sections} notes={aiReady ? reviewData.section_notes : []} />
            </ReportSection>
            <ReportSection id="rc-suggestions" n={5} title="Suggested rewrites" meta={`${suggestions.length} total`}>
              <SuggestionList suggestions={suggestions} />
            </ReportSection>
          </article>
        </div>
      )}
    </div>
  );
}
