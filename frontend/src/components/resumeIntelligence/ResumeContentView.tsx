import { useState } from 'react';

import Icon from '@/components/ui/Icon';
import type { ExperienceEntry, ResumeContent } from '@/types/resumeIntelligence';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
};
const inputStyle: React.CSSProperties = {
  padding: '8px 10px', borderRadius: 'var(--r-sm)', background: 'var(--surface-2)',
  border: '1px solid var(--border)', color: 'var(--text)', font: '600 12.5px/1.4 var(--font)', width: '100%',
};
const label: React.CSSProperties = {
  display: 'block', font: '600 10.5px/1 var(--font)', color: 'var(--text-4)',
  textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 5,
};

function newId() {
  return Math.random().toString(36).slice(2);
}

/**
 * Read/edit view of one résumé's structured content — the shared component behind both the
 * master résumé and every role branch (the same document shape, just a different lineage).
 * Read mode renders like a premium document; edit mode exposes the underlying structure
 * (achievements individually addressable) without turning into a developer-facing JSON editor.
 */
export default function ResumeContentView({ content, editable, onSave, saving }: {
  content: ResumeContent;
  editable: boolean;
  onSave?: (content: ResumeContent) => void;
  saving?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<ResumeContent>(content);

  const startEdit = () => {
    setDraft(content);
    setEditing(true);
  };
  const cancel = () => setEditing(false);
  const save = () => {
    onSave?.(draft);
    setEditing(false);
  };

  if (!editing) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {editable && (
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button onClick={startEdit} style={ghostBtn}><Icon name="file" size={12} /> Edit content</button>
          </div>
        )}
        <ReadSection title="Header">
          <div style={{ font: '700 15px/1.3 var(--font)', color: 'var(--text)' }}>{content.header.full_name || '—'}</div>
          <div style={{ font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
            {[content.header.email, content.header.phone, content.header.location].filter(Boolean).join(' · ') || '—'}
          </div>
        </ReadSection>
        <ReadSection title="Summary">
          <p style={{ margin: 0, font: '500 13px/1.6 var(--font)', color: 'var(--text-2)' }}>{content.summary || '—'}</p>
        </ReadSection>
        <ReadSection title="Experience">
          {content.experience.length === 0 ? <Empty /> : content.experience.map((e) => (
            <div key={e.id} style={{ marginBottom: 12 }}>
              <div style={{ font: '700 13px/1.3 var(--font)', color: 'var(--text)' }}>{e.title} · {e.company}</div>
              <div style={{ font: '500 11px/1.3 var(--font)', color: 'var(--text-4)', marginBottom: 6 }}>{e.start_date} – {e.end_date || 'Present'}</div>
              <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {e.achievements.map((a) => (
                  <li key={a.id} style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>{a.text}</li>
                ))}
              </ul>
            </div>
          ))}
        </ReadSection>
        <ReadSection title="Skills">
          <TagList items={content.skills} />
        </ReadSection>
        {content.certifications.length > 0 && (
          <ReadSection title="Certifications"><TagList items={content.certifications} /></ReadSection>
        )}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button onClick={cancel} style={ghostBtn}>Cancel</button>
        <button onClick={save} disabled={saving} style={primaryBtn}>{saving ? 'Saving…' : 'Save as new version'}</button>
      </div>

      <div style={{ ...card, padding: 14 }}>
        <div style={label as React.CSSProperties}>Full name</div>
        <input style={inputStyle} value={draft.header.full_name} onChange={(e) => setDraft({ ...draft, header: { ...draft.header, full_name: e.target.value } })} />
      </div>

      <div style={{ ...card, padding: 14 }}>
        <div style={label}>Summary</div>
        <textarea
          style={{ ...inputStyle, minHeight: 80, resize: 'vertical', font: '500 12.5px/1.5 var(--font)' }}
          value={draft.summary} onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
        />
      </div>

      <div style={{ ...card, padding: 14 }}>
        <div style={label}>Skills (comma-separated)</div>
        <input
          style={inputStyle} value={draft.skills.join(', ')}
          onChange={(e) => setDraft({ ...draft, skills: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
        />
      </div>

      <div style={{ ...card, padding: 14 }}>
        <div style={label}>Certifications (comma-separated)</div>
        <input
          style={inputStyle} value={draft.certifications.join(', ')}
          onChange={(e) => setDraft({ ...draft, certifications: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
        />
      </div>

      <div style={{ ...card, padding: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <div style={label}>Experience</div>
          <button
            onClick={() => setDraft({ ...draft, experience: [...draft.experience, { id: newId(), title: '', company: '', location: '', start_date: '', end_date: '', achievements: [] }] })}
            style={ghostBtn}
          >
            <Icon name="plus" size={12} /> Add role
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {draft.experience.map((entry, i) => (
            <ExperienceEditor
              key={entry.id}
              entry={entry}
              onChange={(next) => setDraft({ ...draft, experience: draft.experience.map((e, ix) => (ix === i ? next : e)) })}
              onRemove={() => setDraft({ ...draft, experience: draft.experience.filter((_, ix) => ix !== i) })}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function ExperienceEditor({ entry, onChange, onRemove }: {
  entry: ExperienceEntry; onChange: (e: ExperienceEntry) => void; onRemove: () => void;
}) {
  return (
    <div style={{ padding: 12, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginBottom: 8 }}>
        <input style={inputStyle} placeholder="Title" value={entry.title} onChange={(e) => onChange({ ...entry, title: e.target.value })} />
        <input style={inputStyle} placeholder="Company" value={entry.company} onChange={(e) => onChange({ ...entry, company: e.target.value })} />
        <input style={inputStyle} placeholder="Start" value={entry.start_date} onChange={(e) => onChange({ ...entry, start_date: e.target.value })} />
        <input style={inputStyle} placeholder="End (or Present)" value={entry.end_date} onChange={(e) => onChange({ ...entry, end_date: e.target.value })} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {entry.achievements.map((a, ai) => (
          <div key={a.id} style={{ display: 'flex', gap: 6 }}>
            <input
              style={inputStyle} value={a.text}
              onChange={(e) => onChange({ ...entry, achievements: entry.achievements.map((x, xi) => (xi === ai ? { ...x, text: e.target.value } : x)) })}
            />
            <button
              onClick={() => onChange({ ...entry, achievements: entry.achievements.filter((_, xi) => xi !== ai) })}
              style={{ ...ghostBtn, padding: '0 8px' }}
            >
              <Icon name="x" size={11} />
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => onChange({ ...entry, achievements: [...entry.achievements, { id: newId(), text: '', technologies: [], evidence: '' }] })}
            style={ghostBtn}
          >
            <Icon name="plus" size={11} /> Add achievement
          </button>
          <button onClick={onRemove} style={{ ...ghostBtn, color: 'var(--rejected)', marginLeft: 'auto' }}>
            <Icon name="trash" size={11} /> Remove role
          </button>
        </div>
      </div>
    </div>
  );
}

function ReadSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ ...card, padding: 16 }}>
      <div style={{ font: '700 10.5px/1 var(--font)', color: 'var(--text-4)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  );
}

function TagList({ items }: { items: string[] }) {
  if (items.length === 0) return <Empty />;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {items.map((s) => (
        <span key={s} style={{ padding: '4px 10px', borderRadius: 999, background: 'var(--surface-2)', color: 'var(--text-2)', font: '600 11.5px/1 var(--font)' }}>{s}</span>
      ))}
    </div>
  );
}

function Empty() {
  return <p style={{ margin: 0, font: '500 12px/1.4 var(--font)', color: 'var(--text-4)' }}>Nothing recorded yet.</p>;
}

const primaryBtn: React.CSSProperties = {
  height: 32, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'var(--accent)',
  border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12px/1 var(--font)', cursor: 'pointer',
};
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px',
  borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)',
  color: 'var(--text-2)', font: '700 11.5px/1 var(--font)', cursor: 'pointer',
};
