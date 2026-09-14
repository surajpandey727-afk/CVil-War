import { useEffect, useRef, useState } from 'react';

import Icon from '@/components/ui/Icon';
import { cancelConnect, getConnectAttempt, startConnect } from '@/services/settingsService';
import type { ConnectAttempt } from '@/types/platforms';

/** How often to ask the server where the capture has got to. */
const POLL_MS = 1500;

/** How each state reads to the operator, and what it means for the dialog. */
const STATE_COPY: Record<ConnectAttempt['state'], { title: string; tone: string }> = {
  opening: { title: 'Opening a browser window…', tone: 'var(--text-3)' },
  awaiting_login: { title: 'Waiting for you to sign in', tone: 'var(--pending)' },
  capturing: { title: 'Signed in — saving your session…', tone: 'var(--pending)' },
  connected: { title: 'Connected', tone: 'var(--applied)' },
  failed: { title: 'Could not connect', tone: 'var(--rejected)' },
  cancelled: { title: 'Cancelled', tone: 'var(--text-3)' },
  timed_out: { title: 'Timed out', tone: 'var(--rejected)' },
};

/**
 * Guided sign-in for a job platform.
 *
 * The question this screen answers, in the operator's words: "how can you apply if you don't
 * have my credentials?" It never gets them. A real browser window opens on the platform's own
 * login page, the operator signs in there — password, verification code and all — and CVil-War
 * keeps only the resulting session, encrypted. That is stated on the dialog rather than buried
 * in documentation, because a screen that asks you to sign in owes you an account of what it
 * is keeping.
 */
export default function ConnectPlatformDialog({
  platform,
  label,
  onClose,
  onConnected,
}: {
  platform: string;
  label: string;
  onClose: () => void;
  onConnected: () => void;
}) {
  const [attempt, setAttempt] = useState<ConnectAttempt | null>(null);
  const [error, setError] = useState<string>('');
  // Guards the effect against React's double-invoke in development, which would otherwise
  // open two browser windows onto the same login.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async (id: string) => {
      try {
        const next = await getConnectAttempt(id);
        if (cancelled) return;
        setAttempt(next);
        if (next.state === 'connected') {
          onConnected();
          return;
        }
        if (!next.done) timer = setTimeout(() => void poll(id), POLL_MS);
      } catch {
        if (!cancelled) setError('Lost track of the sign-in. Close this and try again.');
      }
    };

    void (async () => {
      try {
        const first = await startConnect(platform);
        if (cancelled) return;
        setAttempt(first);
        if (!first.done) timer = setTimeout(() => void poll(first.id), POLL_MS);
      } catch {
        if (!cancelled) {
          setError(`Could not open a login window for ${label}.`);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [platform, label, onConnected]);

  const onCancel = () => {
    if (attempt && !attempt.done) void cancelConnect(attempt.id).catch(() => undefined);
    onClose();
  };

  const copy = attempt ? STATE_COPY[attempt.state] : null;
  const settled = attempt?.done ?? false;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Connect ${label}`}
      style={{
        position: 'fixed', inset: 0, zIndex: 60, display: 'grid', placeItems: 'center',
        background: 'rgba(0,0,0,.45)', padding: 20,
      }}
    >
      <div style={{
        width: 'min(460px, 100%)', background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-2)', padding: 20,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <span style={{
            display: 'grid', placeItems: 'center', width: 32, height: 32, borderRadius: 9,
            background: 'var(--accent-soft)', color: 'var(--accent)',
          }}>
            <Icon name="plug" size={16} />
          </span>
          <span style={{ font: '700 14px/1.2 var(--font)' }}>Connect {label}</span>
        </div>

        {error ? (
          <p style={{ margin: '0 0 14px', font: '500 12.5px/1.5 var(--font)', color: 'var(--rejected)' }}>
            {error}
          </p>
        ) : (
          <>
            <div style={{ font: '700 12.5px/1.3 var(--font)', color: copy?.tone, marginBottom: 6 }}>
              {copy?.title ?? 'Starting…'}
            </div>
            <p style={{ margin: '0 0 12px', font: '500 12.5px/1.55 var(--font)', color: 'var(--text-3)' }}>
              {attempt?.detail || attempt?.instructions ||
                `A browser window will open on the ${label} login page.`}
            </p>
            {attempt?.state === 'awaiting_login' && attempt.seconds_remaining > 0 && (
              <p style={{ margin: '0 0 12px', font: '500 11px/1.4 var(--mono)', color: 'var(--text-4)' }}>
                {Math.ceil(attempt.seconds_remaining / 60)} min remaining
              </p>
            )}
          </>
        )}

        {/* Stated on the screen that asks for the sign-in, not only in the docs. */}
        <div style={{
          padding: '10px 12px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)',
          border: '1px solid var(--border)', font: '500 11.5px/1.5 var(--font)',
          color: 'var(--text-3)', marginBottom: 14,
        }}>
          You type your password into {label}&rsquo;s own page. CVil-War never sees it, never
          stores it, and keeps only the session cookies for {label} &mdash; encrypted, and
          removable at any time with Disconnect.
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={settled || error ? onClose : onCancel} style={{
            height: 30, padding: '0 13px', borderRadius: 'var(--r-md)', cursor: 'pointer',
            background: 'var(--surface-2)', border: '1px solid var(--border)',
            color: 'var(--text-2)', font: '600 12px/1 var(--font)',
          }}>
            {settled || error ? 'Close' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  );
}
