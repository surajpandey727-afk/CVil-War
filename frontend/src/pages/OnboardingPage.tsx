import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import Logo from '@/components/ui/Logo';
import Icon, { type IconName } from '@/components/ui/Icon';
import { useUploadResume } from '@/hooks/useResumes';
import { useUpdateSettings } from '@/hooks/useSettings';
import { useAppStore } from '@/store/useAppStore';

const PLATFORMS = ['linkedin', 'indeed', 'glassdoor', 'exa'];
const STEP_COUNT = 4;
//: Without at least one, discovery has nothing to search for and a brand-new account sees
//: zero jobs until someone finds Settings and fills this in by hand — see
//: `services.discovery_scheduler._active_titles`, which returns nothing at all with no
//: role targets configured. This step exists so that never happens silently.
const ROLE_TITLE_EXAMPLES = ['Product Manager', 'Data Analyst', 'Software Engineer', 'Data Scientist'];

export default function OnboardingPage() {
  const navigate = useNavigate();
  const notify = useAppStore((s) => s.showNotification);
  const upload = useUploadResume();
  const updateSettings = useUpdateSettings();
  const [step, setStep] = useState(0);
  const [applyMode, setApplyMode] = useState('review');
  const [platforms, setPlatforms] = useState<Set<string>>(new Set(PLATFORMS));
  const [roleTitles, setRoleTitles] = useState<string[]>([]);
  const [roleInput, setRoleInput] = useState('');

  const onUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    upload.mutate(file, { onSuccess: () => notify(`Uploaded · ${file.name}`, 'success'), onError: () => notify('Upload failed', 'error') });
    e.target.value = '';
  };
  const togglePlatform = (p: string) =>
    setPlatforms((prev) => { const n = new Set(prev); if (n.has(p)) n.delete(p); else n.add(p); return n; });

  const addRoleTitle = (title: string) => {
    const trimmed = title.trim();
    if (!trimmed || roleTitles.some((t) => t.toLowerCase() === trimmed.toLowerCase())) return;
    setRoleTitles((prev) => [...prev, trimmed]);
    setRoleInput('');
  };
  const removeRoleTitle = (title: string) => setRoleTitles((prev) => prev.filter((t) => t !== title));
  const onRoleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addRoleTitle(roleInput);
    }
  };

  const finish = () => {
    updateSettings.mutate({
      apply_mode: applyMode,
      platforms_enabled: [...platforms],
      role_targets: roleTitles.map((title) => ({
        title, active: true, fit: 1, why: 'Added during onboarding', family: 'other',
      })),
    });
    navigate('/dashboard');
  };
  const onPrimary = () => (step < STEP_COUNT - 1 ? setStep(step + 1) : finish());
  const primaryLabel = step < STEP_COUNT - 1 ? (step === 0 ? 'Get started' : 'Continue') : 'Go to dashboard';

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'var(--font)', letterSpacing: '-.01em', padding: 20 }}>
      <div style={{ width: '100%', maxWidth: 540 }}>
        {/* Brand + progress */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Logo size={31} />
            <div style={{ font: '800 15px/1 var(--font)', letterSpacing: '-.02em' }}>CVil<span style={{ color: 'var(--accent)' }}>-War</span></div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {Array.from({ length: STEP_COUNT }).map((_, i) => (
              <span key={i} style={{ width: i === step ? 22 : 8, height: 8, borderRadius: 4, background: i <= step ? 'var(--accent)' : 'var(--surface-2)', transition: 'width .2s var(--ease)' }} />
            ))}
          </div>
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-xl)', boxShadow: 'var(--shadow-2)', padding: 28, minHeight: 300, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: '1 1 auto' }}>
            {step === 0 && (
              <>
                <h1 style={{ margin: '0 0 8px', font: '800 24px/1.2 var(--font)', letterSpacing: '-.02em' }}>Welcome to CVil-War</h1>
                <p style={{ margin: '0 0 20px', font: '500 13.5px/1.5 var(--font)', color: 'var(--text-3)' }}>Your job-search copilot searches, tailors, and applies — with you in control. Three quick steps to set it up.</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <Feature icon="file" title="Add your résumé" sub="The agent tailors it per role and scores every match." />
                  <Feature icon="briefcase" title="Search across platforms" sub="LinkedIn, Indeed, Glassdoor, and Exa in one place." />
                  <Feature icon="cpu" title="Apply on autopilot" sub="Review each, batch-approve, or go fully autonomous." />
                </div>
              </>
            )}
            {step === 1 && (
              <>
                <h1 style={{ margin: '0 0 8px', font: '800 22px/1.2 var(--font)', letterSpacing: '-.02em' }}>What roles are you targeting?</h1>
                <p style={{ margin: '0 0 18px', font: '500 13px/1.5 var(--font)', color: 'var(--text-3)' }}>Add at least one job title. This is what the agent searches for — without it, discovery has nothing to look for.</p>
                <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                  <input
                    aria-label="Job title"
                    value={roleInput}
                    onChange={(e) => setRoleInput(e.target.value)}
                    onKeyDown={onRoleInputKeyDown}
                    placeholder="e.g. Product Manager"
                    style={{ flex: '1 1 auto', height: 40, padding: '0 12px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)', color: 'var(--text)', font: '500 13px/1 var(--font)' }}
                  />
                  <button type="button" onClick={() => addRoleTitle(roleInput)} style={{ flex: '0 0 auto', height: 40, padding: '0 16px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}>Add</button>
                </div>
                {roleTitles.length > 0 && (
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
                    {roleTitles.map((title) => (
                      <span key={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 6px 0 12px', borderRadius: 999, background: 'var(--accent-soft)', border: '1px solid var(--accent-line)', color: 'var(--accent)', font: '600 12px/1 var(--font)' }}>
                        {title}
                        <button type="button" aria-label={`Remove ${title}`} onClick={() => removeRoleTitle(title)} style={{ display: 'grid', placeItems: 'center', width: 20, height: 20, borderRadius: '50%', background: 'transparent', border: 0, color: 'inherit', cursor: 'pointer' }}>
                          <Icon name="x" size={12} sw={2.4} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <span style={{ display: 'block', font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 8 }}>Or pick one to start</span>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {ROLE_TITLE_EXAMPLES.filter((t) => !roleTitles.includes(t)).map((title) => (
                    <button key={title} type="button" onClick={() => addRoleTitle(title)} style={{ height: 32, padding: '0 13px', borderRadius: 999, cursor: 'pointer', font: '600 12px/1 var(--font)', border: '1px solid var(--border)', background: 'var(--surface-2)', color: 'var(--text-3)' }}>
                      {title}
                    </button>
                  ))}
                </div>
              </>
            )}
            {step === 2 && (
              <>
                <h1 style={{ margin: '0 0 8px', font: '800 22px/1.2 var(--font)', letterSpacing: '-.02em' }}>Add your résumé</h1>
                <p style={{ margin: '0 0 20px', font: '500 13px/1.5 var(--font)', color: 'var(--text-3)' }}>Upload a base résumé (PDF or DOCX). You can skip this and add one later.</p>
                <label style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: '30px 20px', borderRadius: 'var(--r-lg)', border: '1.5px dashed var(--border-2)', background: 'var(--surface-2)', cursor: 'pointer', textAlign: 'center' }}>
                  <span style={{ display: 'grid', placeItems: 'center', width: 44, height: 44, borderRadius: 12, background: 'var(--accent-soft)', color: 'var(--accent)' }}><Icon name="upload" size={20} sw={2} /></span>
                  <span style={{ font: '700 13px/1.3 var(--font)' }}>{upload.isPending ? 'Uploading…' : 'Click to upload your résumé'}</span>
                  <span style={{ font: '500 11.5px/1.3 var(--font)', color: 'var(--text-4)' }}>PDF or DOCX, up to 10MB</span>
                  <input type="file" accept=".pdf,.docx,.doc" aria-label="Upload résumé" onChange={onUpload} style={{ position: 'absolute', width: 1, height: 1, opacity: 0 }} />
                </label>
              </>
            )}
            {step === 3 && (
              <>
                <h1 style={{ margin: '0 0 8px', font: '800 22px/1.2 var(--font)', letterSpacing: '-.02em' }}>How should the agent apply?</h1>
                <p style={{ margin: '0 0 18px', font: '500 13px/1.5 var(--font)', color: 'var(--text-3)' }}>You can change any of this later in Settings.</p>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 7, marginBottom: 16 }}>
                  <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Apply mode</span>
                  <select aria-label="Apply mode" value={applyMode} onChange={(e) => setApplyMode(e.target.value)} style={{ height: 40, padding: '0 11px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)', color: 'var(--text)', font: '500 13px/1 var(--font)' }}>
                    <option value="review">Review each before applying</option>
                    <option value="batch">Batch-approve</option>
                    <option value="autonomous">Fully autonomous</option>
                  </select>
                </label>
                <span style={{ display: 'block', font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 8 }}>Platforms</span>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {PLATFORMS.map((p) => {
                    const on = platforms.has(p);
                    return (
                      <button key={p} type="button" aria-pressed={on} onClick={() => togglePlatform(p)} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 32, padding: '0 13px', borderRadius: 999, cursor: 'pointer', font: '600 12px/1 var(--font)', textTransform: 'capitalize', border: `1px solid ${on ? 'var(--accent-line)' : 'var(--border)'}`, background: on ? 'var(--accent-soft)' : 'var(--surface-2)', color: on ? 'var(--accent)' : 'var(--text-3)' }}>
                        {on && <Icon name="check" size={12} sw={2.4} />} {p}
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginTop: 24 }}>
            {step > 0 ? (
              <button type="button" onClick={() => setStep(step - 1)} style={{ height: 40, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'transparent', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}>Back</button>
            ) : (
              <button type="button" onClick={() => navigate('/dashboard')} style={{ height: 40, padding: '0 4px', background: 'transparent', border: 0, color: 'var(--text-4)', font: '600 12px/1 var(--font)', cursor: 'pointer' }}>Skip</button>
            )}
            <button type="button" onClick={onPrimary} style={{ height: 40, padding: '0 18px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}>{primaryLabel}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Feature({ icon, title, sub }: { icon: IconName; title: string; sub: string }) {
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
      <span style={{ flex: '0 0 auto', display: 'grid', placeItems: 'center', width: 36, height: 36, borderRadius: 10, background: 'var(--accent-soft)', color: 'var(--accent)' }}><Icon name={icon} size={17} /></span>
      <span>
        <span style={{ display: 'block', font: '700 13px/1.2 var(--font)' }}>{title}</span>
        <span style={{ display: 'block', font: '500 11.5px/1.3 var(--font)', color: 'var(--text-3)', marginTop: 2 }}>{sub}</span>
      </span>
    </div>
  );
}
