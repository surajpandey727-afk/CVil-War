import Icon from '@/components/ui/Icon';
import { atsColor, atsPercent } from '@/lib/status';
import { useResumePreviewUrl } from '@/hooks/useResumes';
import type { Resume, ResumeScoreResponse } from '@/types/resume';
import type { Job } from '@/types/job';

const TYPE_META: Record<string, { label: string; color: string; soft: string }> = {
  base: { label: 'Base', color: 'var(--text-3)', soft: 'var(--surface-2)' },
  tailored: { label: 'Tailored', color: 'var(--interview)', soft: 'var(--interview-soft)' },
  optimized: { label: 'Optimized', color: 'var(--offer)', soft: 'var(--offer-soft)' },
};

interface ResumePreviewPanelProps {
  resume: Resume;
  score: ResumeScoreResponse | null;
  scoring: boolean;
  jobs: Job[];
  targetJobId: string;
  /** The source (base) résumé's stored ATS — the "before" for an optimized variant's delta pill. */
  baseAtsScore?: number | null;
  onSelectJob: (id: string) => void;
  onScore: () => void;
  onDownload: (format: 'pdf' | 'docx') => void;
  onExtractProfile: () => void;
  extractingProfile: boolean;
}

/** Sticky "Preview & score" panel for the selected résumé (design §RÉSUMÉS right column). */
export default function ResumePreviewPanel({ resume, score, scoring, jobs, targetJobId, baseAtsScore, onSelectJob, onScore, onDownload, onExtractProfile, extractingProfile }: ResumePreviewPanelProps) {
  const t = TYPE_META[resume.type] ?? TYPE_META['base']!;
  // Only honor a score that was computed for THIS résumé — the selection can shift (e.g. after a
  // generate/optimize puts a new variant at the top of the list) while a stale score is still held.
  const applicable = score && score.resume_id === resume.id ? score : null;
  const overall = applicable ? atsPercent(applicable.overall_score) : resume.ats_score != null ? atsPercent(resume.ats_score) : 0;
  // Before/after delta (design §RÉSUMÉS): an optimized variant vs its base's stored pre-opt score.
  const afterRaw = applicable ? applicable.overall_score : resume.ats_score;
  const showDelta = resume.type === 'optimized' && baseAtsScore != null && afterRaw != null;
  const wasPct = baseAtsScore != null ? atsPercent(baseAtsScore) : 0;
  const deltaPct = afterRaw != null ? atsPercent(afterRaw) - wasPct : 0;
  const deltaColor = deltaPct >= 0 ? 'var(--offer)' : 'var(--rejected)';
  const deltaSoft = deltaPct >= 0 ? 'var(--offer-soft)' : 'var(--rejected-soft)';
  const subs = applicable
    ? [
        { label: 'Skill', v: atsPercent(applicable.skill_score) },
        { label: 'Keyword', v: atsPercent(applicable.keyword_score) },
        { label: 'Experience', v: atsPercent(applicable.experience_score) },
        { label: 'Education', v: atsPercent(applicable.education_score) },
      ]
    : [];
  const canScore = Boolean(targetJobId) && !scoring;
  const { url: previewUrl, loading: previewLoading, error: previewError } = useResumePreviewUrl(resume.id, resume.has_pdf);

  return (
    <div style={{ position: 'sticky', top: 0, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 16, display: 'flex', flexDirection: 'column', gap: 14, fontFamily: 'var(--font)', color: 'var(--text)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ font: '700 13px/1 var(--font)' }}>Preview &amp; score</span>
        <span style={{ padding: '3px 8px', borderRadius: 6, background: t.soft, color: t.color, font: '700 9px/1 var(--mono)', letterSpacing: '.04em', textTransform: 'uppercase' }}>{t.label}</span>
      </div>

      {resume.has_pdf ? (
        <div style={{ height: 340, borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)', overflow: 'hidden', position: 'relative' }}>
          {previewUrl && (
            <iframe
              key={resume.id}
              src={`${previewUrl}#toolbar=0&navpanes=0`}
              title={`Preview of ${resume.name}`}
              style={{ width: '100%', height: '100%', border: 0, display: 'block', background: '#fff' }}
            />
          )}
          {previewLoading && (
            <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', font: '600 11.5px/1 var(--font)', color: 'var(--text-3)' }}>
              Loading preview…
            </div>
          )}
          {previewError && (
            <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', gap: 6, textAlign: 'center', padding: 16, font: '600 11.5px/1.4 var(--font)', color: 'var(--text-3)' }}>
              <Icon name="alert" size={18} />
              Couldn&apos;t load the preview.
            </div>
          )}
        </div>
      ) : (
        <div style={{ height: 120, borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)', display: 'grid', placeItems: 'center', gap: 6, textAlign: 'center', padding: 16, font: '600 11.5px/1.4 var(--font)', color: 'var(--text-3)' }}>
          <Icon name="file" size={18} />
          No PDF on file yet for this résumé.
        </div>
      )}

      <div style={{ font: '700 12.5px/1.3 var(--font)' }}>{resume.name}</div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div role="img" aria-label={`ATS score ${overall} out of 100`} style={{ flex: '0 0 auto', position: 'relative', width: 70, height: 70 }}>
          <svg viewBox="0 0 76 76" aria-hidden="true" style={{ width: 70, height: 70, transform: 'rotate(-90deg)' }}>
            <circle cx={38} cy={38} r={34} fill="none" stroke="var(--surface-3)" strokeWidth={6} />
            <circle cx={38} cy={38} r={34} fill="none" stroke={atsColor(overall)} strokeWidth={6} strokeLinecap="round" strokeDasharray={2 * Math.PI * 34} strokeDashoffset={2 * Math.PI * 34 * (1 - overall / 100)} />
          </svg>
          <span style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', font: '800 18px/1 var(--mono)', color: atsColor(overall) }}>{overall}</span>
        </div>
        <div style={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', gap: 7 }}>
          {subs.length > 0 ? subs.map((s) => (
            <div key={s.label}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ font: '600 10.5px/1 var(--font)', color: 'var(--text-2)' }}>{s.label}</span>
                <span style={{ font: '700 10.5px/1 var(--mono)' }}>{s.v}</span>
              </div>
              <div style={{ height: 4, borderRadius: 2, background: 'var(--surface-3)', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${s.v}%`, background: atsColor(s.v) }} />
              </div>
            </div>
          )) : (
            <p style={{ margin: 0, font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)' }}>Score this résumé against a job to see the skill / keyword breakdown.</p>
          )}
        </div>
      </div>

      <button onClick={onExtractProfile} disabled={extractingProfile}
        title="Reads this résumé and fills in your work history and education in Settings — the Experience and Education factors above score against that, not the résumé file directly."
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, height: 34, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: extractingProfile ? 'var(--text-4)' : 'var(--text-2)', font: '700 11.5px/1 var(--font)', cursor: extractingProfile ? 'default' : 'pointer' }}>
        <Icon name="wand" size={13} /> {extractingProfile ? 'Reading résumé…' : 'Fill profile from this résumé'}
      </button>

      {showDelta && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, padding: '6px 10px', borderRadius: 8, background: deltaSoft, alignSelf: 'flex-start' }}>
          <span style={{ display: 'grid', placeItems: 'center', color: deltaColor }}><Icon name="arrowUR" size={13} /></span>
          <span style={{ font: '700 11.5px/1 var(--font)', color: deltaColor }}>
            {deltaPct >= 0 ? '+' : ''}{deltaPct} ATS after optimization
          </span>
          <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)' }}>· was {wasPct}</span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <select
          aria-label="Target job"
          value={targetJobId}
          onChange={(e) => onSelectJob(e.target.value)}
          style={{ flex: '1 1 auto', minWidth: 0, height: 36, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)', color: 'var(--text)', font: '600 12px/1 var(--font)', cursor: 'pointer' }}
        >
          <option value="">Select a job…</option>
          {jobs.map((j) => <option key={j.id} value={j.id}>{j.title} · {j.company}</option>)}
        </select>
        <button onClick={onScore} disabled={!canScore}
          style={{ flex: '0 0 auto', height: 36, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: canScore ? 'var(--text)' : 'var(--text-4)', font: '700 12px/1 var(--font)', cursor: canScore ? 'pointer' : 'not-allowed' }}>
          {scoring ? 'Scoring…' : 'Score vs job'}
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={() => onDownload('pdf')} disabled={!resume.has_pdf}
          style={{ flex: '1 1 auto', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, height: 36, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: resume.has_pdf ? 'var(--text-2)' : 'var(--text-4)', font: '700 12px/1 var(--font)', cursor: resume.has_pdf ? 'pointer' : 'not-allowed' }}>
          <Icon name="download" size={14} /> PDF
        </button>
        {resume.has_docx && (
          <button onClick={() => onDownload('docx')}
            style={{ flex: '1 1 auto', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, height: 36, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-2)', font: '700 12px/1 var(--font)', cursor: 'pointer' }}>
            <Icon name="download" size={14} /> DOCX
          </button>
        )}
      </div>
    </div>
  );
}
