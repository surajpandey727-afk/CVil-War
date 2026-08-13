import { useEffect, useMemo, useState } from 'react';

import Icon from '@/components/ui/Icon';
import { useSettings, useUpdateSettings } from '@/hooks/useSettings';
import { useResumes } from '@/hooks/useResumes';
import { useAppStore } from '@/store/useAppStore';
import { DEFAULT_AUTOMATION, type AutomationSettings, type ResumeRule } from '@/types/settings';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

const SENIORITY = ['Junior', 'Mid', 'Senior', 'Lead', 'Principal'];
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOURS = ['06:00', '07:00', '08:00', '09:00', '10:00', '12:00', '14:00', '17:00', '19:00', '21:00', '23:00'];
const TONES: AutomationSettings['cover_letter_tone'][] = ['direct', 'warm', 'formal', 'technical'];

/**
 * Auto-apply policy. Everything on this page is persisted to
 * `UserSettings.automation` and read by the worker before each submission.
 *
 * The page holds a local draft and saves explicitly. An auto-saving policy screen is the wrong
 * shape here: dragging the ATS threshold past 90 for a moment would otherwise be a live rule
 * change against a run already in flight.
 */
export default function AutomationPage() {
  const notify = useAppStore((s) => s.showNotification);
  const { data: settings, isLoading } = useSettings();
  const { data: resumeData } = useResumes();
  const update = useUpdateSettings();

  const resumes = useMemo(() => resumeData?.items ?? [], [resumeData]);
  const [draft, setDraft] = useState<AutomationSettings>(DEFAULT_AUTOMATION);

  useEffect(() => {
    if (settings?.automation) setDraft(settings.automation);
  }, [settings]);

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(settings?.automation ?? DEFAULT_AUTOMATION),
    [draft, settings],
  );

  const patch = (p: Partial<AutomationSettings>) => setDraft((d) => ({ ...d, ...p }));
  const toggleIn = (list: string[], v: string) =>
    list.includes(v) ? list.filter((x) => x !== v) : [...list, v];

  const save = () => {
    update.mutate(
      // `min_ats_score` lives in two places: the top-level column the worker already reads,
      // and the automation blob. Write both so a worker on the old code path stays correct.
      { automation: draft, min_ats_score: draft.min_ats_score },
      {
        onSuccess: () => notify('Automation rules saved. They apply to the next run.', 'success'),
        onError: () => notify('Could not save the automation rules', 'error'),
      },
    );
  };

  const updateRule = (i: number, p: Partial<ResumeRule>) =>
    patch({ resume_rules: draft.resume_rules.map((r, n) => (n === i ? { ...r, ...p } : r)) });

  if (isLoading) {
    return <div style={{ ...card, color: 'var(--text-3)', font: '500 13px/1.4 var(--font)' }}>Loading automation rules…</div>;
  }

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 auto', minWidth: 240 }}>
          <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Automation</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
            Rules the agent follows on every run. Changes apply to the next run, not one in flight.
          </p>
        </div>
        <button
          onClick={save} disabled={!dirty || update.isPending}
          style={{
            height: 36, padding: '0 16px', borderRadius: 'var(--r-md)',
            background: dirty ? 'var(--accent)' : 'var(--surface-2)',
            border: `1px solid ${dirty ? 'var(--accent)' : 'var(--border)'}`,
            color: dirty ? 'var(--accent-ink)' : 'var(--text-3)',
            font: '700 12.5px/1 var(--font)', cursor: dirty ? 'pointer' : 'default',
          }}
        >
          {update.isPending ? 'Saving…' : dirty ? 'Save rules' : 'Saved'}
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <section style={card}>
          <SectionTitle>Match &amp; eligibility</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 20 }}>
            <Range
              label="Minimum ATS match" value={`${Math.round(draft.min_ats_score * 100)}%`}
              min={0} max={95} step={5} current={Math.round(draft.min_ats_score * 100)}
              onChange={(v) => patch({ min_ats_score: v / 100 })}
              note="Postings below this are collected and scored, but never auto-applied to."
            />
            <Range
              label="Minimum salary" value={draft.min_salary_k ? `£${draft.min_salary_k}k` : 'Any'}
              min={0} max={200} step={5} current={draft.min_salary_k}
              onChange={(v) => patch({ min_salary_k: v })}
              note="Postings without a published band are kept and flagged, not dropped."
            />
          </div>
          <Label>SENIORITY</Label>
          <Row>
            {SENIORITY.map((s) => (
              <Chip key={s} on={draft.seniority.includes(s)} onClick={() => patch({ seniority: toggleIn(draft.seniority, s) })}>{s}</Chip>
            ))}
          </Row>
          <Label>BLOCKED COMPANIES</Label>
          <input
            value={draft.blocked_companies.join(', ')}
            placeholder="Comma-separated. Matched case-insensitively on the company name."
            onChange={(e) => patch({ blocked_companies: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) })}
            style={input}
          />
        </section>

        <section style={card}>
          <SectionTitle>Résumé selection</SectionTitle>
          <p style={sub}>First matching rule wins. A role that matches nothing uses the default CV.</p>
          <Label>DEFAULT CV</Label>
          <select
            value={draft.default_resume_id ?? ''}
            onChange={(e) => patch({ default_resume_id: e.target.value || null })}
            style={{ ...input, marginBottom: 16 }}
          >
            <option value="">— none selected —</option>
            {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {draft.resume_rules.map((rule, i) => (
              <div key={i} style={ruleRow}>
                <span style={{ font: '700 10px/1 var(--mono)', color: 'var(--text-4)', width: 20 }}>
                  {String(i + 1).padStart(2, '0')}
                </span>
                <input
                  value={rule.title_pattern} placeholder="Title matches (regex)"
                  onChange={(e) => updateRule(i, { title_pattern: e.target.value })}
                  style={{ ...input, flex: '1 1 180px', height: 32 }}
                />
                <input
                  value={rule.company_pattern} placeholder="Company matches (regex)"
                  onChange={(e) => updateRule(i, { company_pattern: e.target.value })}
                  style={{ ...input, flex: '1 1 150px', height: 32 }}
                />
                <select
                  value={rule.resume_id} onChange={(e) => updateRule(i, { resume_id: e.target.value })}
                  style={{ ...input, flex: '0 1 190px', height: 32 }}
                >
                  <option value="">— pick a CV —</option>
                  {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
                <button
                  onClick={() => patch({ resume_rules: draft.resume_rules.filter((_, n) => n !== i) })}
                  aria-label="Delete rule"
                  style={{ ...iconBtn, color: 'var(--rejected)' }}
                >
                  <Icon name="trash" size={15} />
                </button>
              </div>
            ))}
          </div>
          <button
            onClick={() => patch({ resume_rules: [...draft.resume_rules, { title_pattern: '', company_pattern: '', resume_id: '', label: '' }] })}
            style={{ ...ghost, marginTop: 10, width: 'auto', padding: '0 14px' }}
          >
            Add rule
          </button>
        </section>

        <section style={card}>
          <SectionTitle>Cover letters</SectionTitle>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
            <Switch on={draft.cover_letters} onClick={() => patch({ cover_letters: !draft.cover_letters })} />
            <span style={{ font: '600 12.5px/1 var(--font)', color: 'var(--text-2)' }}>
              {draft.cover_letters
                ? 'Generate a tailored cover letter for every application'
                : 'Cover letters off — apply with the CV only'}
            </span>
          </div>
          <Label>TONE</Label>
          <Row>
            {TONES.map((t) => (
              <Chip key={t} on={draft.cover_letter_tone === t} onClick={() => patch({ cover_letter_tone: t })}>
                {t[0]!.toUpperCase() + t.slice(1)}
              </Chip>
            ))}
          </Row>
        </section>

        <section style={card}>
          <SectionTitle>Failure handling</SectionTitle>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <ToggleRow
              label="Retry failed submissions" on={draft.retry_failed}
              note={`Up to ${draft.max_retries} attempts with backoff, then the fallback.`}
              onClick={() => patch({ retry_failed: !draft.retry_failed })}
            />
            <ToggleRow
              label="Pause on CAPTCHA" on={draft.pause_on_captcha}
              note="Raises an intervention and hands the session to you rather than guessing."
              onClick={() => patch({ pause_on_captcha: !draft.pause_on_captcha })}
            />
            <ToggleRow
              label="Email-apply fallback" on={draft.email_fallback}
              note="Sends CV and cover letter to the posted address when the portal fails."
              onClick={() => patch({ email_fallback: !draft.email_fallback })}
            />
            <ToggleRow
              label="Notify on every outcome" on={draft.notify_each_outcome}
              note="Success and error notifications for each application."
              onClick={() => patch({ notify_each_outcome: !draft.notify_each_outcome })}
            />
          </div>
          <Label>MAX RETRIES</Label>
          <input
            type="range" min={0} max={10} step={1} value={draft.max_retries} aria-label="Max retries"
            onChange={(e) => patch({ max_retries: Number(e.target.value) })}
            style={{ width: 240, accentColor: 'var(--accent)' }}
          />
        </section>

        <section style={card}>
          <SectionTitle>Run window</SectionTitle>
          <p style={sub}>Applications submit only inside these hours ({draft.run_window.timezone}).</p>
          <Row>
            {DAYS.map((d) => (
              <Chip
                key={d} on={draft.run_window.days.includes(d)}
                onClick={() => patch({ run_window: { ...draft.run_window, days: toggleIn(draft.run_window.days, d) } })}
              >
                {d}
              </Chip>
            ))}
          </Row>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 16, flexWrap: 'wrap' }}>
            <span style={{ font: '600 12px/1 var(--font)', color: 'var(--text-2)' }}>Between</span>
            <select
              value={draft.run_window.start} aria-label="Window start"
              onChange={(e) => patch({ run_window: { ...draft.run_window, start: e.target.value } })}
              style={{ ...input, width: 110, height: 36 }}
            >
              {HOURS.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
            <span style={{ font: '600 12px/1 var(--font)', color: 'var(--text-2)' }}>and</span>
            <select
              value={draft.run_window.end} aria-label="Window end"
              onChange={(e) => patch({ run_window: { ...draft.run_window, end: e.target.value } })}
              style={{ ...input, width: 110, height: 36 }}
            >
              {HOURS.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </div>
        </section>
      </div>
    </div>
  );
}

/* -- pieces ------------------------------------------------------------------------- */

const sub: React.CSSProperties = { margin: '0 0 16px', font: '500 12px/1.45 var(--font)', color: 'var(--text-3)' };

const input: React.CSSProperties = {
  height: 36, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)',
  border: '1px solid var(--border)', color: 'var(--text)', font: '600 12.5px/1 var(--font)',
  outline: 'none', width: '100%', minWidth: 0,
};

const ruleRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 'var(--r-md)',
  background: 'var(--surface-2)', border: '1px solid var(--border)', flexWrap: 'wrap',
};

const iconBtn: React.CSSProperties = {
  flex: '0 0 auto', width: 32, height: 32, borderRadius: 'var(--r-sm)', background: 'transparent',
  border: '1px solid var(--border)', cursor: 'pointer', display: 'grid', placeItems: 'center',
};

const ghost: React.CSSProperties = {
  height: 32, borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)',
  color: 'var(--text-2)', font: '600 12px/1 var(--font)', cursor: 'pointer',
};

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div style={{ font: '700 13.5px/1 var(--font)', marginBottom: 12 }}>{children}</div>;
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ font: '600 10px/1 var(--mono)', letterSpacing: '.12em', color: 'var(--text-4)', margin: '16px 0 9px' }}>
      {children}
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>{children}</div>;
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick} aria-pressed={on}
      style={{
        display: 'inline-flex', alignItems: 'center', height: 28, padding: '0 11px', borderRadius: 999,
        cursor: 'pointer', font: '600 11.5px/1 var(--font)',
        border: `1px solid ${on ? 'var(--accent-line)' : 'var(--border)'}`,
        background: on ? 'var(--accent-soft)' : 'var(--surface-2)',
        color: on ? 'var(--accent)' : 'var(--text-3)',
      }}
    >
      {children}
    </button>
  );
}

function Switch({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick} role="switch" aria-checked={on}
      style={{
        flex: '0 0 auto', width: 38, height: 22, borderRadius: 999, padding: 2, cursor: 'pointer',
        border: `1px solid ${on ? 'var(--accent-line)' : 'var(--border)'}`,
        background: on ? 'var(--accent)' : 'var(--surface-3)',
        display: 'flex', alignItems: 'center', justifyContent: on ? 'flex-end' : 'flex-start',
      }}
    >
      <span style={{ display: 'block', width: 16, height: 16, borderRadius: '50%', background: on ? '#fff' : 'var(--text-4)' }} />
    </button>
  );
}

function ToggleRow({ label, note, on, onClick }: { label: string; note: string; on: boolean; onClick: () => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 14px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <div style={{ font: '700 12.5px/1.25 var(--font)', color: 'var(--text)' }}>{label}</div>
        <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>{note}</div>
      </div>
      <Switch on={on} onClick={onClick} />
    </div>
  );
}

function Range({ label, value, min, max, step, current, onChange, note }: {
  label: string; value: string; min: number; max: number; step: number;
  current: number; onChange: (v: number) => void; note: string;
}) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ font: '600 12px/1 var(--font)', color: 'var(--text-2)' }}>{label}</span>
        <span style={{ font: '700 12px/1 var(--mono)', color: 'var(--accent)' }}>{value}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={current} aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: 'var(--accent)' }}
      />
      <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 8 }}>{note}</div>
    </div>
  );
}
