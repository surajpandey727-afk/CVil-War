import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import { useSystemStatus } from '@/hooks/useSystemStatus';
import type { ServiceState } from '@/types/system';

const DOT: Record<string, string> = {
  connected: 'var(--applied)',
  pending: 'var(--review)',
  unavailable: 'var(--rejected)',
  not_configured: 'var(--text-4)',
};

/**
 * One honest status surface for every dependency the app leans on: live updates (websocket),
 * the AI model gateway, Gmail notifications, the job-board sessions, the apply agent and the
 * database. Replaces the bare "Reconnecting…" pill — which only ever reflected a websocket that
 * serverless can never hold open — with a pill you can open to see exactly what is connected,
 * what is pending, and a one-click action to fix each pending thing. Polls every 30s and on open.
 */
export default function SystemStatus({ wsConnected }: { wsConnected: boolean }) {
  const { data, isLoading, refetch, isFetching } = useSystemStatus();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const live: ServiceState = {
    key: 'live', label: 'Live updates',
    status: wsConnected ? 'connected' : 'pending',
    detail: wsConnected
      ? 'Connected — changes appear instantly.'
      : 'Updates refresh every few seconds (live push unavailable here).',
    action_path: '', action_label: '',
  };
  const services = [live, ...(data?.services ?? [])];
  // Live-updates "pending" (no websocket) is not an error — the app still polls — so it does not
  // count toward the attention badge; only genuinely unconnected dependencies do.
  const attention = data?.attention ?? 0;
  const allGood = data?.all_ok ?? false;
  const pillColor = isLoading ? 'var(--text-4)' : attention > 0 ? 'var(--review)' : 'var(--applied)';
  const label = isLoading ? 'Checking…' : attention > 0 ? `${attention} to connect` : 'All connected';

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="System status"
        title="Connection status of Gmail, the AI gateway, job boards and more"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 7, height: 34, padding: '0 12px',
          borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)',
          font: '600 11.5px/1 var(--font)', color: 'var(--text-3)', cursor: 'pointer',
        }}
      >
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: pillColor, animation: allGood ? 'aaPulse 1.8s var(--ease-io) infinite' : 'none' }} />
        {label}
        <span style={{ display: 'inline-flex', transform: open ? 'rotate(-90deg)' : 'rotate(90deg)', transition: 'transform .18s var(--ease)' }}>
          <Icon name="chevR" size={12} />
        </span>
      </button>

      {open && (
        <div
          role="menu"
          style={{
            position: 'absolute', top: 40, right: 0, zIndex: 40, width: 320, padding: 8,
            borderRadius: 'var(--r-lg)', background: 'var(--surface-1)', border: '1px solid var(--border-2)',
            boxShadow: 'var(--shadow-2)', display: 'flex', flexDirection: 'column', gap: 2,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 8px 8px' }}>
            <span style={{ font: '800 12px/1 var(--font)', color: 'var(--text)' }}>System status</span>
            <button
              onClick={() => refetch()}
              title="Re-check now"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5, height: 24, padding: '0 8px', borderRadius: 999, background: 'var(--surface-3)', border: '1px solid var(--border)', color: 'var(--text-3)', font: '600 10.5px/1 var(--font)', cursor: 'pointer' }}
            >
              <Icon name="refresh" size={11} /> {isFetching ? 'Checking…' : 'Recheck'}
            </button>
          </div>
          {services.map((s) => (
            <div key={s.key} style={{ display: 'flex', alignItems: 'flex-start', gap: 9, padding: '8px', borderRadius: 'var(--r-md)', background: 'var(--surface-2)' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: DOT[s.status] ?? 'var(--text-4)', marginTop: 4, flex: '0 0 auto' }} />
              <div style={{ flex: '1 1 auto', minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ font: '700 11.5px/1.2 var(--font)', color: 'var(--text)' }}>{s.label}</span>
                  <span style={{ font: '700 9.5px/1 var(--mono)', letterSpacing: '.04em', textTransform: 'uppercase', color: DOT[s.status] ?? 'var(--text-4)' }}>
                    {s.status.replace('_', ' ')}
                  </span>
                </div>
                <div style={{ font: '500 11px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 2 }}>{s.detail}</div>
              </div>
              {s.action_path && s.action_label && (
                <button
                  onClick={() => { setOpen(false); navigate(s.action_path); }}
                  style={{ flex: '0 0 auto', height: 26, padding: '0 10px', borderRadius: 'var(--r-md)', background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--accent-ink)', font: '700 10.5px/1 var(--font)', cursor: 'pointer' }}
                >
                  {s.action_label}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
