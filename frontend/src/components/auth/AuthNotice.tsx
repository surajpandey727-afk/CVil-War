import type { ReactNode } from 'react';

import Icon, { type IconName } from '@/components/ui/Icon';

interface AuthNoticeProps {
  icon: IconName;
  title: string;
  body: string;
  footer: ReactNode;
}

/** Centered brand card for a terminal auth state (e.g. "check your email", "password reset"). */
export function AuthNotice({ icon, title, body, footer }: AuthNoticeProps) {
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'var(--font)', letterSpacing: '-.01em', padding: 20 }}>
      <div style={{ width: '100%', maxWidth: 400 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'center', marginBottom: 22 }}>
          <div style={{ width: 32, height: 32, borderRadius: 9, background: 'var(--accent-soft)', border: '1px solid var(--accent-line)', display: 'grid', placeItems: 'center', color: 'var(--accent)', boxShadow: 'inset 0 0 14px var(--accent-glow)' }}>
            <Icon name="cpu" size={18} sw={1.9} />
          </div>
          <div style={{ font: '800 17px/1 var(--font)', letterSpacing: '-.02em' }}>AutoApply<span style={{ color: 'var(--accent)' }}> AI</span></div>
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-xl)', boxShadow: 'var(--shadow-2)', padding: 26, textAlign: 'center' }}>
          <div style={{ width: 44, height: 44, margin: '0 auto 14px', borderRadius: 12, background: 'var(--accent-soft)', border: '1px solid var(--accent-line)', display: 'grid', placeItems: 'center', color: 'var(--accent)' }}>
            <Icon name={icon} size={22} />
          </div>
          <h1 style={{ margin: '0 0 6px', font: '800 20px/1.2 var(--font)', letterSpacing: '-.02em' }}>{title}</h1>
          <p style={{ margin: 0, font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>{body}</p>
        </div>

        <div style={{ textAlign: 'center', marginTop: 16, font: '500 12.5px/1.4 var(--font)', color: 'var(--text-3)' }}>{footer}</div>
      </div>
    </div>
  );
}
