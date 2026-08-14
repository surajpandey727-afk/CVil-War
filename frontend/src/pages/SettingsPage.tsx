import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import AISettingsPanel from '@/components/settings/AISettingsPanel';
import PlatformsPanel from '@/components/settings/PlatformsPanel';
import { useSettings, useUpdateSettings } from '@/hooks/useSettings';
import { useAppStore } from '@/store/useAppStore';
import type { Settings } from '@/types/settings';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};
const controlStyle: React.CSSProperties = {
  height: 36, padding: '0 11px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)',
  border: '1px solid var(--border)', color: 'var(--text)', font: '500 12.5px/1 var(--font)', outline: 'none',
};

export default function SettingsPage() {
  const notify = useAppStore((s) => s.showNotification);
  const { data, isError, refetch } = useSettings();
  const [params] = useSearchParams();
  const platformsRef = useRef<HTMLDivElement>(null);

  // Deep link: arriving from Sources -> Manage should put the platform section in front of
  // the operator, not drop them at the top of a long settings page to hunt for it.
  useEffect(() => {
    if (params.get('section') !== 'platforms') return;
    platformsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [params]);
  const update = useUpdateSettings();
  const [draft, setDraft] = useState<Settings | null>(null);

  useEffect(() => {
    if (data) setDraft(data);
  }, [data]);

  if (isError && !draft) {
    return (
      <div style={{ ...card, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '40px 20px', textAlign: 'center' }}>
        <span style={{ color: 'var(--failed)', display: 'grid', placeItems: 'center' }}><Icon name="alert" size={18} /></span>
        <span style={{ font: '600 13px/1.4 var(--font)', color: 'var(--text-2)' }}>Couldn't load your settings.</span>
        <button
          onClick={() => void refetch()}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 34, padding: '0 16px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!draft) {
    return <div style={{ ...card, height: 120, background: 'linear-gradient(90deg,var(--surface-2),var(--hover),var(--surface-2))', backgroundSize: '200% 100%', animation: 'aaShimmer 1.3s linear infinite' }} />;
  }

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setDraft({ ...draft, [key]: value });
  const save = () =>
    update.mutate(draft, {
      onSuccess: () => notify('Settings saved', 'success'),
      onError: () => notify('Could not save settings', 'error'),
    });

  return (
    <div style={{ animation: 'aaUp .4s var(--ease) both', maxWidth: 760 }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, font: '800 24px/1.1 var(--font)', letterSpacing: '-.03em' }}>Settings</h1>
          <p style={{ margin: '6px 0 0', font: '500 13px/1.4 var(--font)', color: 'var(--text-3)' }}>Tune how the agent applies, which platforms it searches, and your AI keys.</p>
        </div>
        <button onClick={save} disabled={update.isPending} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 38, padding: '0 16px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}>
          <Icon name="check" size={14} sw={2.2} /> {update.isPending ? 'Saving…' : 'Save'}
        </button>
      </div>

      {/* Apply preferences */}
      <section style={{ ...card, marginBottom: 14 }}>
        <SectionTitle icon="cpu" title="Apply preferences" sub="Control the autonomy of the apply agent." />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 14, marginTop: 14 }}>
          <Field label="Apply mode">
            <select aria-label="Apply mode" value={draft.apply_mode} onChange={(e) => set('apply_mode', e.target.value)} style={controlStyle}>
              <option value="review">Review each</option>
              <option value="autonomous">Autonomous</option>
              <option value="batch">Batch approve</option>
            </select>
          </Field>
          <Field label={`Min ATS score · ${Math.round(draft.min_ats_score * 100)}`}>
            <input type="range" min={0} max={100} value={Math.round(draft.min_ats_score * 100)} onChange={(e) => set('min_ats_score', Number(e.target.value) / 100)} aria-label="Minimum ATS score" style={{ accentColor: 'var(--accent)', width: '100%' }} />
          </Field>
          <Field label="Max parallel runs">
            <input type="number" min={1} max={10} value={draft.max_parallel} onChange={(e) => set('max_parallel', Number(e.target.value))} aria-label="Max parallel" style={controlStyle} />
          </Field>
        </div>
      </section>

      {/* Platforms. Deep-linkable as /settings?section=platforms, because "Manage" on the
          Sources screen used to land here with no indication of where to look. */}
      <div ref={platformsRef}>
        <PlatformsPanel />
      </div>

      {/* AI providers and usage — discovered from the gateway, summed from real calls. */}
      <AISettingsPanel />
    </div>
  );
}

function SectionTitle({ icon, title, sub }: { icon: 'cpu' | 'briefcase'; title: string; sub: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
      <span style={{ display: 'grid', placeItems: 'center', width: 32, height: 32, borderRadius: 9, background: 'var(--accent-soft)', color: 'var(--accent)' }}><Icon name={icon} size={16} /></span>
      <span>
        <span style={{ display: 'block', font: '700 14px/1.2 var(--font)', letterSpacing: '-.01em' }}>{title}</span>
        <span style={{ display: 'block', font: '500 11.5px/1.3 var(--font)', color: 'var(--text-3)', marginTop: 2 }}>{sub}</span>
      </span>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</span>
      {children}
    </label>
  );
}
