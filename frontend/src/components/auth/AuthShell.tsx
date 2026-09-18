import type { FormEvent, ReactNode } from 'react';

import Icon from '@/components/ui/Icon';
import Logo from '@/components/ui/Logo';

interface AuthShellProps {
  title: string;
  subtitle: string;
  error?: string | null;
  submitLabel: string;
  submitting?: boolean;
  onSubmit: (e: FormEvent) => void;
  children: ReactNode;
  footer: ReactNode;
}

/** Centered brand card used by the sign-in / register screens. */
export function AuthShell({ title, subtitle, error, submitLabel, submitting, onSubmit, children, footer }: AuthShellProps) {
  return (
    <div className="leather-deep" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'var(--font)', letterSpacing: '-.01em', padding: 20, position: 'relative' }}>
      <div style={{ width: '100%', maxWidth: 400, position: 'relative' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'center', marginBottom: 24 }}>
          <div style={{ width: 34, height: 34, borderRadius: 'var(--r-md)', background: 'var(--surface)', display: 'grid', placeItems: 'center', color: 'var(--accent)', boxShadow: 'var(--neu-out-sm)' }}>
            <Logo size={30} />
          </div>
          <div style={{ font: '800 17px/1 var(--font)', letterSpacing: '-.02em' }}>CVil<span style={{ color: 'var(--accent)' }}>-War</span></div>
        </div>

        <form onSubmit={onSubmit} className="leather" style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-xl)', boxShadow: 'var(--neu-out)', padding: 28 }}>
          <h1 style={{ margin: '0 0 5px', font: '800 21px/1.2 var(--font)', letterSpacing: '-.02em' }}>{title}</h1>
          <p style={{ margin: '0 0 22px', font: '500 12.5px/1.4 var(--font)', color: 'var(--text-3)' }}>{subtitle}</p>
          {error && (
            <div role="alert" style={{ display: 'flex', gap: 9, alignItems: 'center', padding: '10px 12px', marginBottom: 16, borderRadius: 'var(--r-md)', background: 'var(--rejected-soft)', border: '1px solid var(--rejected)', color: 'var(--rejected)', font: '600 12px/1.35 var(--font)' }}>
              <Icon name="alert" size={15} /> {error}
            </div>
          )}
          {children}
          <button type="submit" disabled={submitting} style={{ width: '100%', height: 44, marginTop: 8, borderRadius: 'var(--r-md)', background: 'var(--accent)', border: 'none', color: 'var(--accent-ink)', font: '700 13px/1 var(--font)', cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1, boxShadow: submitting ? 'var(--neu-pressed)' : '-3px -3px 8px rgba(250,231,201,.12), 4px 4px 12px rgba(0,0,0,.4)', transition: 'box-shadow .15s var(--ease)' }}>
            {submitLabel}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 18, font: '500 12.5px/1.4 var(--font)', color: 'var(--text-3)' }}>{footer}</div>
      </div>
    </div>
  );
}

interface AuthFieldProps {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  autoComplete?: string;
  required?: boolean;
}

export function AuthField({ id, label, type = 'text', value, onChange, autoComplete, required }: AuthFieldProps) {
  return (
    <label htmlFor={id} style={{ display: 'flex', flexDirection: 'column', gap: 7, marginBottom: 14 }}>
      <span style={{ font: '600 11.5px/1 var(--font)', color: 'var(--text-2)' }}>{label}</span>
      <input
        id={id}
        type={type}
        value={value}
        onChange={onChange}
        autoComplete={autoComplete}
        required={required}
        style={{ height: 42, padding: '0 13px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)', boxShadow: 'var(--neu-in-sm)', color: 'var(--text)', font: '500 13px/1 var(--font)', outline: 'none' }}
      />
    </label>
  );
}
