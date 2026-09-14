import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import AgentGraphView from '@/components/agents/AgentGraphView';
import Icon from '@/components/ui/Icon';
import { usePolicyCatalogue, usePolicyPreview, useSettings, useUpdateSettings } from '@/hooks/useSettings';
import { useResumes } from '@/hooks/useResumes';
import { useAppStore } from '@/store/useAppStore';
import {
  DEFAULT_AUTOMATION,
  type AutomationSettings,
  type PolicyGroup,
  type PolicyPreview,
  type PolicyRuleInfo,
  type ResumeRule,
  type RunWindow,
} from '@/types/settings';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOURS = ['00:00', '06:00', '07:00', '08:00', '09:00', '10:00', '12:00', '14:00', '17:00', '19:00', '21:00', '23:00', '23:59'];

/**
 * The automation policy screen.
 *
 * Every control here is rendered from the rule catalogue the backend serves at
 * `/settings/automation-policy`, not from a hard-coded list. That is the whole design: the
 * written policy (`docs/AUTOMATION_POLICY.md`), the rules the worker enforces, and this
 * screen were three places the same thing could be stated, and they drifted — the page
 * claimed the worker read these settings for months while it did not. Now a clause exists
 * once, and its control, bounds, clause reference and rationale all travel with it.
 *
 * The page holds a local draft and saves explicitly. An auto-saving policy screen is the
 * wrong shape here: dragging the ATS threshold past 90 for a moment would otherwise be a
 * live rule change against a run already in flight.
 */
type Tab = 'policy' | 'ops';

export default function AutomationPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const tab: Tab = tabParam === 'ops' ? 'ops' : 'policy';
  const setTab = (next: Tab) => setSearchParams(next === 'policy' ? {} : { tab: next });

  const notify = useAppStore((s) => s.showNotification);
  const { data: settings } = useSettings();
  const { data: catalogue, isLoading, isError, refetch } = usePolicyCatalogue();
  const { data: resumeData } = useResumes();
  const update = useUpdateSettings();
  const preview = usePolicyPreview();

  const resumes = useMemo(() => resumeData?.items ?? [], [resumeData]);
  const [draft, setDraft] = useState<AutomationSettings>(DEFAULT_AUTOMATION);
  const [previewResult, setPreviewResult] = useState<PolicyPreview | null>(null);

  // Merged over the defaults rather than replacing them. A stored policy written before a
  // clause existed simply omits it, and reading that omission as undefined crashed the page
  // outright on `resume_rules.map` — the same version-skew the backend is careful to survive
  // has to be survivable here too.
  const merged = useMemo(
    () => (catalogue?.policy ? { ...DEFAULT_AUTOMATION, ...catalogue.policy } : null),
    [catalogue],
  );

  useEffect(() => {
    if (merged) setDraft(merged);
  }, [merged]);

  const saved = merged ?? settings?.automation ?? DEFAULT_AUTOMATION;
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(saved), [draft, saved]);

  const setField = (field: string, value: unknown) => {
    setDraft((d) => ({ ...d, [field]: value }));
    // A preview describes the policy it was run against. Leaving it on screen after an edit
    // would show numbers that no longer correspond to anything.
    setPreviewResult(null);
  };

  const save = () => {
    update.mutate(
      // `min_ats_score` lives in two places: the top-level column and the policy blob. Write
      // both so nothing reading the column alone sees a stale threshold.
      { automation: draft, min_ats_score: draft.min_ats_score },
      {
        onSuccess: () => {
          void refetch();
          notify('Policy saved. It applies to the next run, not one in flight.', 'success');
        },
        onError: () => notify('Could not save the policy', 'error'),
      },
    );
  };

  const runPreview = () => {
    preview.mutate(draft, {
      onSuccess: setPreviewResult,
      onError: () => notify('Could not preview the policy against your queue', 'error'),
    });
  };

  const updateRule = (i: number, p: Partial<ResumeRule>) =>
    setField('resume_rules', draft.resume_rules.map((r, n) => (n === i ? { ...r, ...p } : r)));

  const tabBar = (
    <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
      <TabButton active={tab === 'policy'} onClick={() => setTab('policy')}>Policy</TabButton>
      <TabButton active={tab === 'ops'} onClick={() => setTab('ops')}>Agent ops</TabButton>
    </div>
  );

  if (tab === 'ops') {
    return (
      <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1000 }}>
        <div style={{ marginBottom: 18 }}>
          <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Automation</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
            The rules the agent runs under, and the agents that carry them out.
          </p>
        </div>
        {tabBar}
        <AgentGraphView />
      </div>
    );
  }

  if (isLoading) {
    return <div style={{ ...card, color: 'var(--text-3)', font: '500 13px/1.4 var(--font)' }}>Loading the automation policy…</div>;
  }

  if (isError || !catalogue) {
    // Distinguished from an empty policy on purpose: "no rules loaded" and "no rules apply"
    // look identical on screen and mean opposite things.
    return (
      <div style={{ ...card, borderColor: 'var(--rejected)' }}>
        <div style={{ font: '700 13.5px/1.3 var(--font)', marginBottom: 6 }}>
          The policy could not be loaded
        </div>
        <p style={{ margin: '0 0 12px', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
          Nothing here is showing your live rules. The worker still enforces whatever is
          stored — this screen just cannot read it right now.
        </p>
        <button onClick={() => void refetch()} style={{ ...ghost, padding: '0 14px', width: 'auto' }}>
          Try again
        </button>
      </div>
    );
  }

  const paused = draft.paused === true;

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 auto', minWidth: 240 }}>
          <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Automation policy</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>
            The rules the agent runs under. Every one is checked before each submission and
            the decision is written to that application&rsquo;s timeline. Changes apply to the
            next run, not one in flight.
          </p>
        </div>
        <button
          onClick={runPreview} disabled={preview.isPending}
          style={{ ...ghost, height: 36, padding: '0 14px', width: 'auto' }}
        >
          {preview.isPending ? 'Checking…' : 'Test against my queue'}
        </button>
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
          {update.isPending ? 'Saving…' : dirty ? 'Save policy' : 'Saved'}
        </button>
      </div>

      {tabBar}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <section
          style={{
            ...card, display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
            borderColor: paused ? 'var(--rejected)' : 'var(--border)',
          }}
        >
          <Switch on={!paused} onClick={() => setField('paused', !paused)} label="Automation running" />
          <div style={{ flex: '1 1 220px', minWidth: 0 }}>
            <div style={{ font: '700 13px/1.3 var(--font)' }}>
              {paused ? 'Automation is paused' : 'Automation is running'}
            </div>
            <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>
              {paused
                ? 'Nothing is being submitted. Everything queued stays queued and resumes where it left off.'
                : 'Submissions go out whenever every rule below is satisfied.'}
            </div>
          </div>
          {dirty && (
            <span style={{ font: '600 11px/1 var(--font)', color: 'var(--pending)' }}>
              Unsaved — takes effect once you save
            </span>
          )}
        </section>

        {previewResult && <PreviewPanel result={previewResult} onDismiss={() => setPreviewResult(null)} />}

        {catalogue.groups.map((group) => (
          <GroupCard
            key={group.id}
            group={group}
            draft={draft}
            onChange={setField}
            // The kill switch has its own banner above; repeating it inside the oversight
            // group would give one control two positions that could disagree on screen.
            hide={['oversight.kill_switch']}
          />
        ))}

        <section style={card}>
          <SectionTitle>Résumé selection</SectionTitle>
          <p style={sub}>First matching rule wins. A role that matches nothing uses the default CV.</p>
          <Label>DEFAULT CV</Label>
          <select
            value={draft.default_resume_id ?? ''}
            aria-label="Default CV"
            onChange={(e) => setField('default_resume_id', e.target.value || null)}
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
                  value={rule.resume_id} aria-label={`CV for rule ${i + 1}`}
                  onChange={(e) => updateRule(i, { resume_id: e.target.value })}
                  style={{ ...input, flex: '0 1 190px', height: 32 }}
                >
                  <option value="">— pick a CV —</option>
                  {resumes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
                <button
                  onClick={() => setField('resume_rules', draft.resume_rules.filter((_, n) => n !== i))}
                  aria-label="Delete rule"
                  style={{ ...iconBtn, color: 'var(--rejected)' }}
                >
                  <Icon name="trash" size={15} />
                </button>
              </div>
            ))}
          </div>
          <button
            onClick={() => setField('resume_rules', [...draft.resume_rules, { title_pattern: '', company_pattern: '', resume_id: '', label: '' }])}
            style={{ ...ghost, marginTop: 10, width: 'auto', padding: '0 14px' }}
          >
            Add rule
          </button>
        </section>

        <p style={{ margin: 0, font: '500 11.5px/1.5 var(--font)', color: 'var(--text-4)' }}>
          Policy version {catalogue.policy_version}. The written standard is{' '}
          <code style={{ font: '600 11px var(--mono)' }}>{catalogue.document}</code>; each rule
          above cites its clause.
        </p>
      </div>
    </div>
  );
}

/* -- groups and controls ------------------------------------------------------------ */

function GroupCard({ group, draft, onChange, hide }: {
  group: PolicyGroup;
  draft: AutomationSettings;
  onChange: (field: string, value: unknown) => void;
  hide: string[];
}) {
  const rules = group.rules.filter((r) => !hide.includes(r.id));
  if (rules.length === 0) return null;
  return (
    <section style={card}>
      <SectionTitle>{group.title}</SectionTitle>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {rules.map((rule) => (
          <RuleRow key={rule.id} rule={rule} draft={draft} onChange={onChange} />
        ))}
      </div>
    </section>
  );
}

function RuleRow({ rule, draft, onChange }: {
  rule: PolicyRuleInfo;
  draft: AutomationSettings;
  onChange: (field: string, value: unknown) => void;
}) {
  const value = rule.field_name ? draft[rule.field_name] : undefined;
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div style={{ flex: '1 1 300px', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ font: '700 12.5px/1.25 var(--font)', color: 'var(--text)' }}>{rule.title}</span>
          <span style={{ font: '600 10px/1 var(--mono)', color: 'var(--text-4)' }}>{rule.clause}</span>
          {rule.locked && <Badge tone="locked">Locked</Badge>}
          {rule.enforcement === 'behaviour' && !rule.locked && <Badge tone="quiet">Behaviour</Badge>}
          {rule.enforcement === 'gate' && !rule.locked && <Badge tone={rule.verdict}>{rule.verdict}</Badge>}
        </div>
        <div style={{ font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)', marginTop: 4 }}>
          {rule.rationale}
        </div>
        {rule.enforced_by && (
          <div style={{ font: '500 11px/1.4 var(--mono)', color: 'var(--text-4)', marginTop: 4 }}>
            Enforced by {rule.enforced_by}
          </div>
        )}
      </div>
      <div style={{ flex: '0 1 300px', minWidth: 220 }}>
        <Control rule={rule} value={value} onChange={onChange} />
      </div>
    </div>
  );
}

function Control({ rule, value, onChange }: {
  rule: PolicyRuleInfo;
  value: unknown;
  onChange: (field: string, value: unknown) => void;
}) {
  const { control, field_name: field, title } = rule;

  switch (control.kind) {
    case 'locked':
      return (
        <div style={{ font: '600 11.5px/1.4 var(--font)', color: 'var(--text-4)', textAlign: 'right' }}>
          Always on — not configurable
        </div>
      );

    case 'toggle':
      return (
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Switch on={value === true} onClick={() => onChange(field, !value)} label={title} />
        </div>
      );

    case 'percent':
      return (
        <Slider
          label={title} unit={control.unit}
          display={`${Math.round(Number(value) * 100)}%`}
          min={control.min ?? 0} max={control.max ?? 100} step={control.step ?? 1}
          current={Math.round(Number(value) * 100)}
          onChange={(v) => onChange(field, v / 100)}
        />
      );

    case 'integer':
    case 'days':
    case 'seconds':
    case 'money_k': {
      const n = Number(value ?? 0);
      // 0 is the documented "off" value for every numeric limit, so it is shown as such
      // rather than as a limit of zero — which reads as "block everything".
      const off = control.kind === 'money_k' ? 'Any' : 'Off';
      const shown = control.kind === 'money_k' ? `£${n}k` : `${n} ${control.unit}`.trim();
      return (
        <Slider
          label={title} unit={control.unit} display={n === 0 ? off : shown}
          min={control.min ?? 0} max={control.max ?? 100} step={control.step ?? 1}
          current={n} onChange={(v) => onChange(field, v)}
        />
      );
    }

    case 'choice':
      return (
        <Row justify="flex-end">
          {control.options.map((o) => (
            <Chip key={o} on={value === o} onClick={() => onChange(field, o)}>
              {o[0]!.toUpperCase() + o.slice(1)}
            </Chip>
          ))}
        </Row>
      );

    case 'multi_choice': {
      const selected = Array.isArray(value) ? (value as string[]) : [];
      return (
        <Row justify="flex-end">
          {control.options.map((o) => (
            <Chip
              key={o} on={selected.includes(o)}
              onClick={() => onChange(field, selected.includes(o) ? selected.filter((x) => x !== o) : [...selected, o])}
            >
              {o}
            </Chip>
          ))}
        </Row>
      );
    }

    case 'text_list': {
      const list = Array.isArray(value) ? (value as string[]) : [];
      return (
        <input
          value={list.join(', ')} aria-label={title}
          placeholder="Comma-separated"
          onChange={(e) => onChange(field, e.target.value.split(',').map((x) => x.trim()).filter(Boolean))}
          style={input}
        />
      );
    }

    case 'weekdays': {
      const win = (value ?? {}) as RunWindow;
      const days = win.days ?? [];
      const patch = (p: Partial<RunWindow>) => onChange(field, { ...win, ...p });
      return (
        <div>
          <Row justify="flex-end">
            {(control.options.length ? control.options : DAYS).map((d) => (
              <Chip
                key={d} on={days.includes(d)}
                onClick={() => patch({ days: days.includes(d) ? days.filter((x) => x !== d) : [...days, d] })}
              >
                {d}
              </Chip>
            ))}
          </Row>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, justifyContent: 'flex-end' }}>
            <select
              value={win.start} aria-label="Window start"
              onChange={(e) => patch({ start: e.target.value })}
              style={{ ...input, width: 96, height: 32 }}
            >
              {HOURS.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
            <span style={{ font: '600 11.5px/1 var(--font)', color: 'var(--text-3)' }}>to</span>
            <select
              value={win.end} aria-label="Window end"
              onChange={(e) => patch({ end: e.target.value })}
              style={{ ...input, width: 96, height: 32 }}
            >
              {HOURS.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </div>
          <div style={{ font: '500 11px/1.4 var(--font)', color: 'var(--text-4)', marginTop: 6, textAlign: 'right' }}>
            {days.length === 0 ? 'Every day' : days.join(', ')} · {win.timezone}
          </div>
        </div>
      );
    }

    default:
      // A control kind this build does not know how to render. Saying so beats showing
      // nothing, which would look like the rule did not exist.
      return (
        <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-4)', textAlign: 'right' }}>
          Not editable here (control type “{control.kind}”)
        </div>
      );
  }
}

/* -- preview ------------------------------------------------------------------------ */

const VERDICT_LABEL: Record<string, string> = {
  allow: 'would go out',
  hold: 'held for later',
  escalate: 'sent to you',
  block: 'stopped',
};

function PreviewPanel({ result, onDismiss }: { result: PolicyPreview; onDismiss: () => void }) {
  const refused = result.items.filter((i) => i.verdict !== 'allow');
  return (
    <section style={{ ...card, borderColor: 'var(--accent-line)', background: 'var(--accent-soft)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <SectionTitle>What this policy would do right now</SectionTitle>
        <button onClick={onDismiss} style={{ ...ghost, marginLeft: 'auto', height: 26, width: 'auto', padding: '0 10px' }}>
          Dismiss
        </button>
      </div>
      {result.evaluated === 0 ? (
        <p style={{ margin: 0, font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
          Nothing is waiting, so there is nothing to test against. Queue an application and
          run this again to see the effect before you commit to it.
        </p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            {(['allow', 'hold', 'escalate', 'block'] as const).map((v) => (
              <span key={v} style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, height: 26, padding: '0 10px',
                borderRadius: 999, background: 'var(--surface)', border: '1px solid var(--border)',
                font: '600 11.5px/1 var(--font)', color: 'var(--text-2)',
              }}>
                <strong style={{ font: '700 12px/1 var(--mono)' }}>{result[v]}</strong> {VERDICT_LABEL[v]}
              </span>
            ))}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {refused.slice(0, 8).map((item) => (
              <div key={item.application_id} style={{
                padding: '9px 11px', borderRadius: 'var(--r-md)', background: 'var(--surface)',
                border: '1px solid var(--border)',
              }}>
                <div style={{ font: '700 12px/1.3 var(--font)' }}>
                  {item.job_title || 'Untitled role'}
                  {item.company && <span style={{ color: 'var(--text-3)', fontWeight: 500 }}> · {item.company}</span>}
                </div>
                {/* The backend's reason, verbatim. Re-wording it here is how a UI ends up
                    explaining a decision it did not make. */}
                {item.reasons.map((reason, i) => (
                  <div key={i} style={{ font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>
                    {reason}
                  </div>
                ))}
              </div>
            ))}
            {refused.length > 8 && (
              <div style={{ font: '500 11.5px/1.4 var(--font)', color: 'var(--text-4)' }}>
                …and {refused.length - 8} more.
              </div>
            )}
            {refused.length === 0 && (
              <div style={{ font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
                Every waiting application satisfies this policy.
              </div>
            )}
          </div>
        </>
      )}
    </section>
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

const BADGE_TONE: Record<string, { bg: string; fg: string }> = {
  locked: { bg: 'var(--surface-3)', fg: 'var(--text-3)' },
  quiet: { bg: 'var(--surface-3)', fg: 'var(--text-4)' },
  hold: { bg: 'var(--surface-3)', fg: 'var(--pending)' },
  escalate: { bg: 'var(--surface-3)', fg: 'var(--accent)' },
  block: { bg: 'var(--surface-3)', fg: 'var(--rejected)' },
  allow: { bg: 'var(--surface-3)', fg: 'var(--text-4)' },
};

function Badge({ tone, children }: { tone: string; children: React.ReactNode }) {
  const c = BADGE_TONE[tone] ?? BADGE_TONE.quiet!;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', height: 17, padding: '0 6px', borderRadius: 4,
      background: c.bg, color: c.fg, font: '700 9.5px/1 var(--mono)', letterSpacing: '.06em',
      textTransform: 'uppercase',
    }}>
      {children}
    </span>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      style={{
        height: 34, padding: '0 14px', borderRadius: 'var(--r-md)',
        border: `1px solid ${active ? 'var(--accent-line)' : 'var(--border)'}`,
        background: active ? 'var(--accent-soft)' : 'var(--surface-2)',
        color: active ? 'var(--accent)' : 'var(--text-3)', font: '700 12.5px/1 var(--font)', cursor: 'pointer',
      }}
    >
      {children}
    </button>
  );
}

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

function Row({ children, justify = 'flex-start' }: { children: React.ReactNode; justify?: string }) {
  return <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', justifyContent: justify }}>{children}</div>;
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

function Switch({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick} role="switch" aria-checked={on} aria-label={label}
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

function Slider({ label, display, min, max, step, current, onChange }: {
  label: string; unit: string; display: string;
  min: number; max: number; step: number; current: number; onChange: (v: number) => void;
}) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
        <span style={{ font: '700 12px/1 var(--mono)', color: 'var(--accent)' }}>{display}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={current} aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: 'var(--accent)' }}
      />
    </div>
  );
}
