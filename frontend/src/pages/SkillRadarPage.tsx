/** Skill Radar — pick target roles, see the skills they share, score a résumé against them.
 *
 *  The flow the owner asked for: select roles (AI PM, Product Analyst, Technical PM, ...), read
 *  the aggregated in-demand skills and ATS keywords, pick a résumé, run a match, and judge it
 *  against the 60-70% "decent" bar with a ranked list of what to add. Works from a curated
 *  knowledge base when the corpus is empty, and enriches with live demand from stored jobs.
 */
import { useMemo, useState } from 'react';

import Icon from '@/components/ui/Icon';
import RolePicker from '@/components/skills/RolePicker';
import DemandGrid from '@/components/skills/DemandGrid';
import ScorePanel from '@/components/skills/ScorePanel';
import { useSkillRoles, useAggregatedSkills, useScoreResumeSkills } from '@/hooks/useSkills';
import { useResumes } from '@/hooks/useResumes';
import { useAppStore } from '@/store/useAppStore';
import { apiErrorMessage } from '@/lib/apiError';
import type { SkillScoreResponse } from '@/types/skills';

/** Seeded so the page is never blank on arrival — the owner's strongest cluster. */
const DEFAULT_ROLES = ['AI Product Manager', 'Product Manager', 'Product Analyst', 'Technical Product Manager'];

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

export default function SkillRadarPage() {
  const notify = useAppStore((s) => s.showNotification);
  const { data: roleList } = useSkillRoles();
  const { data: resumeData } = useResumes();
  const score = useScoreResumeSkills();

  const [selected, setSelected] = useState<string[]>(DEFAULT_ROLES);
  const [resumeId, setResumeId] = useState('');
  const [result, setResult] = useState<SkillScoreResponse | null>(null);

  const { data: agg, isLoading: aggLoading } = useAggregatedSkills(selected);
  const resumes = useMemo(() => (resumeData?.items ?? []).filter((r) => !r.archived), [resumeData]);
  const roles = roleList ?? DEFAULT_ROLES;

  const coverage = useMemo(() => {
    if (!result) return undefined;
    return new Map(result.hits.map((h) => [h.key, h.present]));
  }, [result]);

  const toggle = (t: string) =>
    setSelected((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));

  const runMatch = () => {
    if (!resumeId || !selected.length) return;
    score.mutate(
      { resumeId, titles: selected },
      {
        onSuccess: (r) => {
          setResult(r);
          const pct = Math.round(r.score * 100);
          notify(`${r.resume_name}: ${pct}% match across ${selected.length} roles`, pct >= 60 ? 'success' : 'info');
        },
        onError: (e) => notify(apiErrorMessage(e, 'Could not score this résumé'), 'error'),
      },
    );
  };

  // A new role selection invalidates a prior score (it was against different roles).
  const onToggleRole = (t: string) => { setResult(null); toggle(t); };
  const onSetRoles = (titles: string[]) => { setResult(null); setSelected(titles); };

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ display: 'grid', placeItems: 'center', width: 34, height: 34, borderRadius: 10, background: 'var(--accent-soft)', color: 'var(--accent-2)' }}>
            <Icon name="gauge" size={18} />
          </span>
          <h1 style={{ font: '800 20px/1 var(--font)', color: 'var(--text)', margin: 0 }}>Skill Radar</h1>
        </div>
        <p style={{ font: '500 13px/1.5 var(--font)', color: 'var(--text-3)', margin: '8px 0 0', maxWidth: 680 }}>
          Pick the roles you&apos;re targeting to see the skills and ATS keywords they share — then
          score a résumé against them. 60–70% means you&apos;ve got most of it covered.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 320px) 1fr', gap: 16, alignItems: 'start' }} className="sr-grid">
        {/* Left: role selection + scoring */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            <SectionTitle>1 · Target roles</SectionTitle>
            <RolePicker roles={roles} selected={selected} onToggle={onToggleRole} onSetMany={onSetRoles} onClear={() => onSetRoles([])} />
          </div>
          <div style={card}>
            <SectionTitle>2 · Score a résumé</SectionTitle>
            {resumes.length === 0 ? (
              <EmptyResumes />
            ) : (
              <ScorePanel
                resumes={resumes} selectedResumeId={resumeId} onSelectResume={setResumeId}
                onRun={runMatch} running={score.isPending} result={result} disabled={!selected.length}
              />
            )}
          </div>
        </div>

        {/* Right: the aggregated demand (becomes a gap view once scored) */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14, gap: 10, flexWrap: 'wrap' }}>
            <SectionTitle noMargin>{result ? 'Your coverage' : 'What these roles want'}</SectionTitle>
            {agg?.corpus_used && (
              <span style={{ font: '600 10px/1 var(--mono)', color: 'var(--applied)' }}>
                enriched from your stored jobs
              </span>
            )}
          </div>
          {!selected.length ? (
            <Hint>Select at least one role on the left to see its most in-demand skills.</Hint>
          ) : aggLoading ? (
            <Hint>Loading demand…</Hint>
          ) : agg && agg.skills.length ? (
            <DemandGrid skills={agg.skills} categories={agg.categories} corpusUsed={agg.corpus_used} coverage={coverage} />
          ) : (
            <Hint>No skills found for this selection.</Hint>
          )}
        </div>
      </div>

      <style>{`@media (max-width: 860px){ .sr-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

function SectionTitle({ children, noMargin }: { children: React.ReactNode; noMargin?: boolean }) {
  return (
    <div style={{ font: '700 12.5px/1 var(--font)', color: 'var(--text-2)', marginBottom: noMargin ? 0 : 14 }}>
      {children}
    </div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--text-4)', padding: '18px 0' }}>{children}</div>;
}

function EmptyResumes() {
  return (
    <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--text-4)' }}>
      Upload a résumé on the Résumés page first, then come back to score it against these roles.
    </div>
  );
}
