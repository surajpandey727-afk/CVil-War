import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import { useJob } from '@/hooks/useJobs';
import { useCommitTailor, useTailorJob } from '@/hooks/useResumeIntelligence';
import { useAppStore } from '@/store/useAppStore';
import { atsColor } from '@/lib/status';
import type { ChangeDecision, ProposedChangeOut } from '@/types/resumeIntelligence';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};

type Decision = 'accept' | 'reject' | 'edit';

/**
 * The core "Tailor résumé" review flow: job analysis (matched/partial/missing, title fit,
 * positioning) then a per-change accept/edit/reject review — nothing is ever applied
 * automatically. Committing creates exactly one new version from whatever was accepted.
 */
export default function TailorReview({ branchId, initialJobId }: {
  branchId: string; initialJobId?: string;
}) {
  const notify = useAppStore((s) => s.showNotification);
  const navigate = useNavigate();
  const { data: job } = useJob(initialJobId);
  const tailor = useTailorJob(initialJobId, branchId);
  const commit = useCommitTailor();
  const [decisions, setDecisions] = useState<Record<string, { decision: Decision; text: string }>>({});
  const [commitMessage, setCommitMessage] = useState('');
  const [committed, setCommitted] = useState<{ label: string; before: number | null; after: number | null } | null>(null);

  if (!initialJobId) {
    return (
      <div style={{ ...card, padding: '30px 20px', textAlign: 'center' }}>
        <p style={{ margin: '0 0 12px', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
          Tailoring starts from a job. Open one in Jobs and click "Tailor résumé".
        </p>
        <button onClick={() => navigate('/jobs')} style={primaryBtn}>Go to Jobs</button>
      </div>
    );
  }

  if (tailor.isPending) {
    return (
      <div style={{ ...card, padding: '30px 20px', textAlign: 'center', color: 'var(--text-3)' }}>
        <p style={{ margin: 0, font: '500 12.5px/1.5 var(--font)' }}>Analysing {job?.title ?? 'this job'}…</p>
      </div>
    );
  }

  if (tailor.isError || !tailor.data) {
    return (
      <div style={{ ...card, padding: '30px 20px', textAlign: 'center' }}>
        <p style={{ margin: '0 0 12px', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>Could not analyse this job.</p>
        <button onClick={() => void tailor.refetch()} style={primaryBtn}>Try again</button>
      </div>
    );
  }

  const result = tailor.data;
  const pct = result.ats_alignment_pct != null ? Math.round(result.ats_alignment_pct) : null;

  const setDecision = (change: ProposedChangeOut, decision: Decision, text?: string) =>
    setDecisions((prev) => ({ ...prev, [change.id]: { decision, text: text ?? prev[change.id]?.text ?? change.after_text ?? '' } }));

  const acceptedCount = result.proposed_changes.filter((c) => (decisions[c.id]?.decision ?? 'accept') !== 'reject').length;

  const doCommit = () => {
    const payload: ChangeDecision[] = result.proposed_changes.map((c) => {
      const d = decisions[c.id];
      if (!d || d.decision === 'accept') return { change_id: c.id, decision: 'accept' };
      if (d.decision === 'reject') return { change_id: c.id, decision: 'reject' };
      return { change_id: c.id, decision: 'edit', edited_after_text: d.text };
    });
    commit.mutate(
      { analysisId: result.analysis_id, decisions: payload, commitMessage: commitMessage || `Tailored for ${job?.title ?? 'this role'}` },
      {
        onSuccess: (r) => {
          setCommitted({ label: r.version.version_label, before: r.ats_alignment_before, after: r.ats_alignment_after });
          notify(`Committed as ${r.version.version_label}`, 'success');
        },
        onError: () => notify('Could not commit these changes', 'error'),
      },
    );
  };

  if (committed) {
    return (
      <div style={{ ...card, padding: 20, textAlign: 'center' }}>
        <div style={{ color: 'var(--applied)', marginBottom: 10 }}><Icon name="check" size={22} /></div>
        <div style={{ font: '800 16px/1.3 var(--font)', color: 'var(--text)', marginBottom: 6 }}>{committed.label} committed</div>
        {committed.after != null && (
          <p style={{ margin: '0 0 4px', font: '600 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>
            ATS alignment: {committed.before != null ? `${Math.round(committed.before)}% → ` : ''}{committed.after}%
          </p>
        )}
        <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
          Go to Applications to submit using this version, or keep refining from Version history.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ ...card, padding: 16, display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        {pct != null && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: '0 0 auto' }}>
            <span style={{ font: '800 26px/1 var(--font)', color: atsColor(pct) }}>{pct}%</span>
            <span style={{ font: '600 9px/1 var(--mono)', letterSpacing: '.08em', color: 'var(--text-4)' }}>ALIGNMENT</span>
          </div>
        )}
        <div style={{ flex: '1 1 220px' }}>
          <div style={{ font: '700 13px/1.3 var(--font)', color: 'var(--text)' }}>{job?.title ?? 'This role'} {job?.company ? `· ${job.company}` : ''}</div>
          <p style={{ margin: '4px 0 0', font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>{result.role_fit_notes}</p>
        </div>
      </div>

      {result.title_analysis && (
        <div style={{ ...card, padding: 16 }}>
          <div style={{ font: '700 10.5px/1 var(--font)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 8 }}>Title analysis</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
            <span style={{ font: '700 12.5px/1.3 var(--font)' }}>{result.title_analysis.current_title || 'Your title'}</span>
            <Icon name="arrowUR" size={12} />
            <span style={{ font: '700 12.5px/1.3 var(--font)' }}>{result.title_analysis.target_title}</span>
            <span style={{ padding: '2px 8px', borderRadius: 999, background: 'var(--surface-2)', font: '700 10.5px/1 var(--font)', color: 'var(--text-3)', textTransform: 'capitalize' }}>
              {result.title_analysis.relationship}
            </span>
          </div>
          {result.title_analysis.positioning_opportunity && (
            <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: 'var(--text-2)' }}>{result.title_analysis.positioning_opportunity}</p>
          )}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 12 }}>
        <SkillBucket title="Matched" tone="var(--applied)" icon="check" items={result.matched} />
        <SkillBucket title="Partial" tone="var(--review)" icon="alert" items={result.partial} />
        <SkillBucket title="Missing" tone="var(--rejected)" icon="x" items={result.missing} />
      </div>

      {result.proposed_changes.length > 0 && (
        <div style={{ ...card, padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
            <div style={{ font: '700 13px/1.3 var(--font)' }}>{result.proposed_changes.length} proposed change{result.proposed_changes.length === 1 ? '' : 's'}</div>
            <div style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)' }}>{acceptedCount} will be committed</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {result.proposed_changes.map((change) => (
              <ChangeReviewRow
                key={change.id} change={change}
                decision={decisions[change.id]?.decision ?? 'accept'}
                editedText={decisions[change.id]?.text ?? change.after_text ?? ''}
                onAccept={() => setDecision(change, 'accept')}
                onReject={() => setDecision(change, 'reject')}
                onEdit={(text) => setDecision(change, 'edit', text)}
              />
            ))}
          </div>

          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              value={commitMessage} onChange={(e) => setCommitMessage(e.target.value)}
              placeholder={`Align résumé with ${job?.title ?? 'this role'}`}
              style={{ flex: '1 1 240px', height: 34, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)', font: '600 12px/1 var(--font)' }}
            />
            <button onClick={doCommit} disabled={commit.isPending || acceptedCount === 0} style={primaryBtn}>
              {commit.isPending ? 'Committing…' : `Commit version`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SkillBucket({ title, tone, icon, items }: { title: string; tone: string; icon: 'check' | 'alert' | 'x'; items: Record<string, string> }) {
  const entries = Object.entries(items);
  return (
    <div style={{ ...card, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <span style={{ color: tone }}><Icon name={icon} size={13} /></span>
        <span style={{ font: '700 11px/1 var(--font)', color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '.04em' }}>{title}</span>
        <span style={{ font: '600 10.5px/1 var(--mono)', color: 'var(--text-4)' }}>({entries.length})</span>
      </div>
      {entries.length === 0 ? (
        <p style={{ margin: 0, font: '500 11.5px/1.4 var(--font)', color: 'var(--text-4)' }}>None</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {entries.map(([skill, evidence]) => (
            <div key={skill}>
              <span style={{ font: '700 12px/1.3 var(--font)', color: 'var(--text)' }}>{skill}</span>
              <span style={{ display: 'block', font: '500 10.5px/1.3 var(--font)', color: 'var(--text-4)' }}>{evidence}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ChangeReviewRow({ change, decision, editedText, onAccept, onReject, onEdit }: {
  change: ProposedChangeOut; decision: Decision; editedText: string;
  onAccept: () => void; onReject: () => void; onEdit: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <div style={{
      padding: 12, borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
      border: `1px solid ${decision === 'reject' ? 'var(--border)' : 'var(--accent-line)'}`,
      opacity: decision === 'reject' ? 0.6 : 1,
    }}>
      <div style={{ font: '600 10px/1 var(--mono)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 6 }}>
        {change.section} · {change.change_type.replace(/_/g, ' ')}
      </div>
      {change.before_text && (
        <div style={{ font: '500 12px/1.5 var(--font)', color: 'var(--text-4)', textDecoration: 'line-through', marginBottom: 4 }}>{change.before_text}</div>
      )}
      {editing ? (
        <textarea
          value={editedText} onChange={(e) => onEdit(e.target.value)}
          style={{ width: '100%', minHeight: 60, padding: 8, borderRadius: 'var(--r-sm)', background: 'var(--surface-3)', border: '1px solid var(--border)', color: 'var(--text)', font: '500 12.5px/1.5 var(--font)', resize: 'vertical' }}
        />
      ) : (
        <div style={{ font: '600 12.5px/1.5 var(--font)', color: 'var(--text)' }}>{decision === 'edit' ? editedText : change.after_text}</div>
      )}
      <p style={{ margin: '6px 0 0', font: '500 11px/1.4 var(--font)', color: 'var(--text-3)' }}>
        <strong style={{ color: 'var(--text-4)' }}>Why:</strong> {change.reason}
      </p>
      {change.evidence && (
        <p style={{ margin: '2px 0 0', font: '500 11px/1.4 var(--font)', color: 'var(--text-3)' }}>
          <strong style={{ color: 'var(--text-4)' }}>Evidence:</strong> {change.evidence}
        </p>
      )}
      {!change.before_text && (change.section === 'experience' || change.section === 'projects') && (
        <p style={{ margin: '6px 0 0', font: '600 11px/1.4 var(--font)', color: 'var(--review)' }}>
          A new {change.section} entry isn't written to the résumé automatically, even if accepted —
          add the real, verified entry yourself (use Edit) so no unverified detail slips in as fact.
        </p>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <TinyBtn active={decision === 'accept'} onClick={onAccept} label="Accept" tone="applied" />
        <TinyBtn
          active={decision === 'edit'}
          onClick={() => { setEditing(true); onEdit(editedText); }}
          label="Edit" tone="review"
        />
        <TinyBtn active={decision === 'reject'} onClick={() => { setEditing(false); onReject(); }} label="Reject" tone="rejected" />
      </div>
    </div>
  );
}

function TinyBtn({ active, onClick, label, tone }: { active: boolean; onClick: () => void; label: string; tone: 'applied' | 'review' | 'rejected' }) {
  return (
    <button
      onClick={onClick}
      style={{
        height: 26, padding: '0 10px', borderRadius: 999, cursor: 'pointer', font: '700 11px/1 var(--font)',
        border: `1px solid ${active ? `var(--${tone})` : 'var(--border)'}`,
        background: active ? `var(--${tone}-soft)` : 'var(--surface-3)',
        color: active ? `var(--${tone})` : 'var(--text-3)',
      }}
    >
      {label}
    </button>
  );
}

const primaryBtn: React.CSSProperties = {
  height: 34, padding: '0 16px', borderRadius: 'var(--r-md)', background: 'var(--accent)',
  border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer',
};
