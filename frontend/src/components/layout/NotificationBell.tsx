/** The header bell: unread badge plus a panel of recent notifications (new jobs, best matches,
 *  applications sent, failed, or waiting on you). Styled to sit beside the cost pill as an
 *  equal, so the header keeps its shape. */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from '@/hooks/useNotifications';
import { relativeTime } from '@/lib/status';
import type { AppNotification } from '@/types/notifications';

const TONE: Record<string, string> = {
  success: 'var(--applied)',
  warning: 'var(--review)',
  critical: 'var(--rejected)',
  info: 'var(--accent)',
};

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { data, isError } = useNotifications();
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllNotificationsRead();
  const unread = data?.unread ?? 0;

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const openItem = (n: AppNotification) => {
    if (!n.read_at) markRead.mutate(n.id);
    setOpen(false);
    if (n.link) navigate(n.link);
  };

  return (
    <div ref={ref} style={{ position: 'relative', flex: '0 0 auto' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        aria-haspopup="dialog"
        style={{
          position: 'relative', width: 34, height: 34, display: 'grid', placeItems: 'center',
          borderRadius: 'var(--r-md)', background: 'var(--surface-3)', border: '1px solid var(--border)',
          color: unread ? 'var(--text)' : 'var(--text-3)', cursor: 'pointer',
        }}
      >
        <Icon name="bell" size={16} />
        {unread > 0 && (
          <span
            aria-hidden="true"
            style={{
              position: 'absolute', top: -5, right: -5, minWidth: 17, height: 17, padding: '0 4px',
              borderRadius: 9, background: 'var(--accent)', color: 'var(--bg)',
              font: '700 10px/17px var(--mono)', textAlign: 'center',
            }}
          >
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          style={{
            position: 'absolute', top: 42, right: 0, width: 'min(380px, calc(100vw - 24px))',
            maxHeight: 'min(520px, calc(100vh - 90px))', display: 'flex', flexDirection: 'column',
            background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)',
            boxShadow: 'var(--shadow-pop)', overflow: 'hidden', zIndex: 40,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
            <span style={{ font: '700 13px/1 var(--font)', color: 'var(--text)', flex: '1 1 auto' }}>Notifications</span>
            {unread > 0 && (
              <button
                onClick={() => markAll.mutate()}
                style={{ background: 'none', border: 'none', color: 'var(--accent)', font: '600 12px/1 var(--font)', cursor: 'pointer', padding: 4 }}
              >
                Mark all read
              </button>
            )}
          </div>

          <ul aria-live="polite" style={{ listStyle: 'none', margin: 0, padding: 0, overflowY: 'auto', minHeight: 0 }}>
            {isError && (
              <li style={{ padding: 16, font: '500 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>
                Couldn&apos;t load notifications. They&apos;ll retry shortly.
              </li>
            )}
            {!isError && data && data.items.length === 0 && (
              <li style={{ padding: 16, font: '500 12.5px/1.5 var(--font)', color: 'var(--text-2)' }}>
                Nothing yet. New UK jobs, strong matches and application updates will appear here.
              </li>
            )}
            {data?.items.map((n) => (
              <li key={n.id}>
                <button
                  onClick={() => openItem(n)}
                  style={{
                    width: '100%', display: 'grid', gridTemplateColumns: '10px minmax(0,1fr) auto', gap: 10,
                    alignItems: 'start', padding: '11px 14px', textAlign: 'left', cursor: 'pointer',
                    background: n.read_at ? 'transparent' : 'color-mix(in srgb, var(--accent) 7%, transparent)',
                    border: 'none', borderBottom: '1px solid var(--border)', color: 'var(--text)',
                  }}
                >
                  <span aria-hidden="true" style={{ width: 8, height: 8, marginTop: 5, borderRadius: 4, background: TONE[n.severity] ?? TONE.info, opacity: n.read_at ? 0.45 : 1 }} />
                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: 'block', font: `${n.read_at ? 500 : 700} 12.5px/1.35 var(--font)`, color: 'var(--text)' }}>{n.title}</span>
                    {n.body && (
                      <span style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', marginTop: 3, font: '500 12px/1.45 var(--font)', color: 'var(--text-2)' }}>
                        {n.body}
                      </span>
                    )}
                    {n.emailed_at && <span style={{ display: 'block', marginTop: 4, font: '600 10.5px/1 var(--mono)', color: 'var(--text-3)' }}>Also emailed</span>}
                  </span>
                  <span style={{ font: '600 10.5px/1.4 var(--mono)', color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{relativeTime(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>

          <button
            onClick={() => { setOpen(false); navigate('/communications'); }}
            style={{ padding: '10px 14px', background: 'var(--surface-2)', border: 'none', borderTop: '1px solid var(--border)', color: 'var(--text-2)', font: '600 11.5px/1.3 var(--font)', textAlign: 'left', cursor: 'pointer' }}
          >
            Email copies go to your Gmail once it&apos;s connected in Communications →
          </button>
        </div>
      )}
    </div>
  );
}
