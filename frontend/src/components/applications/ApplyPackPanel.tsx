/** The application pack: employer link, the CV to attach, and answers to the usual UK form
 *  questions, each copyable. Answers the CV can't evidence are marked "Add only if true" and
 *  are never presented as facts. Styled like the page's other inline panels. */
import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import { useApplyPack } from '@/hooks/useApplyPack';
import { downloadResumeFile } from '@/services/resumeService';
import { atsPercent } from '@/lib/status';
import type { PackAnswer } from '@/types/applyPack';

const box: React.CSSProperties = {
  marginTop: 14, padding: 14, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)',
};
const small: React.CSSProperties = { font: '500 12px/1.5 var(--font)', color: 'var(--text-2)', margin: 0 };

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => { void navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }); }}
      style={{ flex: '0 0 auto', height: 26, padding: '0 9px', borderRadius: 'var(--r-sm)', background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text-2)', font: '600 11px/1 var(--font)', cursor: 'pointer' }}
    >
      {done ? 'Copied' : 'Copy'}
    </button>
  );
}

function AnswerRow({ a }: { a: PackAnswer }) {
  const unverified = a.evidence_status === 'add_only_if_true';
  return (
    <li style={{ padding: '10px 0', borderTop: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ font: '700 12px/1.4 var(--font)', color: 'var(--text)' }}>{a.question}</div>
          <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--text)', marginTop: 3, overflowWrap: 'anywhere' }}>{a.answer}</div>
          {unverified && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginTop: 5, font: '700 10.5px/1 var(--mono)', color: 'var(--review)' }}>
              <Icon name="alert" size={12} /> ADD ONLY IF TRUE
            </div>
          )}
          {a.note && <p style={{ ...small, marginTop: 4 }}>{a.note}</p>}
        </div>
        <CopyButton text={a.answer} />
      </div>
    </li>
  );
}

export default function ApplyPackPanel({ applicationId }: { applicationId: string }) {
  const { data: pack, isLoading, isError } = useApplyPack(applicationId, true);

  if (isLoading) return <div style={box}><p style={small}>Preparing the pack…</p></div>;
  if (isError || !pack) return <div style={box}><p style={small}>Couldn&apos;t prepare the pack. Try again shortly.</p></div>;

  const cvMatch = pack.cv?.download_path.match(/resumes\/([^/]+)\/download\?format=(pdf|docx)/);
  return (
    <section style={box} aria-label="Application pack">
      <div style={{ font: '700 12.5px/1 var(--font)', marginBottom: 8 }}>Application pack</div>
      {pack.manual_reason && <p style={{ ...small, marginBottom: 10 }}>{pack.manual_reason}</p>}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        {pack.employer_url && (
          <a href={pack.employer_url} target="_blank" rel="noreferrer noopener"
             style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 32, padding: '0 12px', borderRadius: 'var(--r-md)', background: 'var(--accent)', color: 'var(--accent-ink)', font: '700 12px/1 var(--font)', textDecoration: 'none' }}>
            <Icon name="briefcase" size={14} /> Open employer page
          </a>
        )}
        {pack.cv && cvMatch && (
          <button type="button" onClick={() => { void downloadResumeFile(cvMatch[1] ?? '', (cvMatch[2] ?? 'pdf') as 'pdf' | 'docx', pack.cv?.name ?? 'cv'); }}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 32, padding: '0 12px', borderRadius: 'var(--r-md)', background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)', font: '700 12px/1 var(--font)', cursor: 'pointer' }}>
            <Icon name="file" size={14} /> Download CV ({pack.cv.name})
          </button>
        )}
        {pack.fit_overall != null && (
          <span style={{ alignSelf: 'center', font: '600 11.5px/1 var(--mono)', color: 'var(--text-3)' }}>fit {atsPercent(pack.fit_overall)}/100</span>
        )}
      </div>

      <ol style={{ margin: '0 0 6px', paddingLeft: 18 }}>
        {pack.checklist.map((c) => <li key={c} style={{ ...small, color: 'var(--text)' }}>{c}</li>)}
      </ol>

      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {pack.answers.map((a) => <AnswerRow key={a.question} a={a} />)}
      </ul>
    </section>
  );
}
