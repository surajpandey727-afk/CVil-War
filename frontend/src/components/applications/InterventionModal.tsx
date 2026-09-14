import { useState, type FormEvent } from 'react';

import Icon from '@/components/ui/Icon';
import { useResolveBlocker, useResolveIntervention } from '@/hooks/useApplications';
import { useAppStore } from '@/store/useAppStore';

/** Global CAPTCHA/2FA intervention modal.
 *
 * Two distinct kinds, because they resolve differently: a 2FA/OTP challenge is a text code
 * typed here and relayed to the worker still waiting on it; a CAPTCHA cannot be solved that
 * way (whoever solves it has to be looking at the same browser session the automation drove),
 * so that run already paused — this shows the page it stopped on and a "Resume" button that
 * re-queues a fresh, headed attempt once the operator has cleared it themselves.
 */
export default function InterventionModal() {
  const iv = useAppStore((s) => s.pendingIntervention);
  const clear = useAppStore((s) => s.clearIntervention);
  const notify = useAppStore((s) => s.showNotification);
  const resolve = useResolveIntervention();
  const resolveBlocker = useResolveBlocker();
  const [value, setValue] = useState('');

  if (!iv) return null;

  const isCaptcha = iv.kind === 'captcha';
  const isSubmitConfirmation = iv.kind === 'submit_confirmation';

  const submit = (e: FormEvent) => {
    e.preventDefault();
    resolve.mutate(
      { appId: iv.application_id, response: value },
      {
        onSuccess: () => { notify('Verification submitted — agent resuming', 'success'); setValue(''); clear(); },
        onError: () => notify('Could not deliver your response', 'error'),
      },
    );
  };

  const resume = () => {
    resolveBlocker.mutate(iv.application_id, {
      onSuccess: () => { notify('Resuming — a browser window will open shortly', 'success'); clear(); },
      onError: () => notify('Could not resume this application', 'error'),
    });
  };

  const respondToSubmission = (response: 'approved' | 'rejected') => {
    resolve.mutate(
      { appId: iv.application_id, response },
      {
        onSuccess: () => {
          notify(
            response === 'approved' ? 'Approved — submitting now' : 'Rejected — the application was not sent',
            response === 'approved' ? 'success' : 'info',
          );
          clear();
        },
        onError: () => notify('Could not deliver your response', 'error'),
      },
    );
  };

  const disabled = resolve.isPending || !value.trim();

  return (
    <div role="presentation" style={{ position: 'fixed', inset: 0, zIndex: 120, background: 'rgba(0,0,0,.55)', backdropFilter: 'blur(2px)', display: 'grid', placeItems: 'center', padding: 20 }}>
      <div role="dialog" aria-label="Action needed" style={{ width: isSubmitConfirmation ? 'min(94vw,560px)' : 'min(94vw,440px)', background: 'var(--surface)', border: '1px solid var(--review-line)', borderRadius: 'var(--r-xl)', boxShadow: 'var(--shadow-pop)', overflow: 'hidden', animation: 'aaPop .18s var(--ease)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '16px 18px', borderBottom: '1px solid var(--border)', background: 'var(--review-soft)' }}>
          <span style={{ display: 'grid', placeItems: 'center', width: 34, height: 34, borderRadius: 9, background: 'var(--surface)', color: 'var(--review)', border: '1px solid var(--review-line)' }}><Icon name="alert" size={18} /></span>
          <span>
            <span style={{ display: 'block', font: '700 14px/1.2 var(--font)' }}>{isSubmitConfirmation ? 'Ready to submit' : 'Action needed'}</span>
            <span style={{ display: 'block', font: '600 10.5px/1 var(--mono)', letterSpacing: '.06em', color: 'var(--review)', marginTop: 3, textTransform: 'uppercase' }}>{iv.kind}</span>
          </span>
        </div>

        {isSubmitConfirmation ? (
          <div style={{ padding: 18 }}>
            <p style={{ margin: '0 0 12px', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>{iv.prompt}</p>
            {iv.screenshot_b64 && (
              <div style={{ marginBottom: 14, borderRadius: 'var(--r-md)', overflow: 'hidden', border: '1px solid var(--border-2)' }}>
                <img
                  src={`data:image/png;base64,${iv.screenshot_b64}`}
                  alt="The form the agent is about to submit"
                  style={{ display: 'block', width: '100%', maxHeight: 360, objectFit: 'contain', background: 'var(--surface-3)' }}
                />
              </div>
            )}
            {iv.url && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginBottom: 16 }}>
                <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Page</span>
                <span style={{ padding: '10px 12px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '500 12px/1.4 var(--mono)', wordBreak: 'break-all' }}>{iv.url}</span>
              </div>
            )}
            <div style={{ display: 'flex', gap: 9 }}>
              <button type="button" onClick={() => respondToSubmission('rejected')} disabled={resolve.isPending} style={{ flex: '1 1 auto', height: 40, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'transparent', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '700 12.5px/1 var(--font)', cursor: resolve.isPending ? 'default' : 'pointer', opacity: resolve.isPending ? 0.6 : 1 }}>
                Reject — don't submit
              </button>
              <button type="button" onClick={() => respondToSubmission('approved')} disabled={resolve.isPending} style={{ flex: '1 1 auto', height: 40, borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: resolve.isPending ? 'default' : 'pointer', opacity: resolve.isPending ? 0.6 : 1 }}>
                {resolve.isPending ? 'Sending…' : 'Approve & submit'}
              </button>
            </div>
          </div>
        ) : isCaptcha ? (
          <div style={{ padding: 18 }}>
            <p style={{ margin: '0 0 12px', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>{iv.prompt}</p>
            <p style={{ margin: '0 0 14px', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>
              A browser window has opened for this application — switch to it, complete the
              verification there, then come back and press Resume.
            </p>
            {iv.url && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginBottom: 16 }}>
                <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Page</span>
                <span style={{ padding: '10px 12px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '500 12px/1.4 var(--mono)', wordBreak: 'break-all' }}>{iv.url}</span>
              </div>
            )}
            <div style={{ display: 'flex', gap: 9 }}>
              <button type="button" onClick={clear} style={{ flex: '0 0 auto', height: 40, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'transparent', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}>Dismiss</button>
              <button type="button" onClick={resume} disabled={resolveBlocker.isPending} style={{ flex: '1 1 auto', height: 40, borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: resolveBlocker.isPending ? 'default' : 'pointer', opacity: resolveBlocker.isPending ? 0.6 : 1 }}>
                {resolveBlocker.isPending ? 'Resuming…' : "I've completed it — Resume"}
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} style={{ padding: 18 }}>
            <p style={{ margin: '0 0 14px', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>{iv.prompt}</p>
            <label htmlFor="iv-input" style={{ display: 'flex', flexDirection: 'column', gap: 7, marginBottom: 16 }}>
              <span style={{ font: '600 11px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Your response</span>
              <input
                id="iv-input"
                value={value}
                onChange={(e) => setValue(e.target.value.toUpperCase())}
                autoFocus
                placeholder="Enter the code shown in the browser"
                style={{ height: 42, padding: '0 12px', borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border-2)', color: 'var(--text)', font: '600 15px/1 var(--mono)', letterSpacing: '.14em', outline: 'none' }}
              />
            </label>
            <div style={{ display: 'flex', gap: 9 }}>
              <button type="button" onClick={clear} style={{ flex: '0 0 auto', height: 40, padding: '0 14px', borderRadius: 'var(--r-md)', background: 'transparent', border: '1px solid var(--border-2)', color: 'var(--text-2)', font: '700 12.5px/1 var(--font)', cursor: 'pointer' }}>Dismiss</button>
              <button type="submit" disabled={disabled} style={{ flex: '1 1 auto', height: 40, borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 12.5px/1 var(--font)', cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.6 : 1 }}>
                {resolve.isPending ? 'Submitting…' : 'Submit verification'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
