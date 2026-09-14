import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import { useResumeRecommendation } from '@/hooks/useJobs';
import { useFocusStore } from '@/store/useFocusStore';

const STORAGE_KEY = 'ats-widget-position';
const COLLAPSED_KEY = 'ats-widget-collapsed';

interface Position {
  x: number;
  y: number;
}

function loadPosition(): Position {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as Position;
  } catch {
    // localStorage can throw in a private window or with site data blocked — fall through.
  }
  return { x: window.innerWidth - 320, y: window.innerHeight - 220 };
}

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * Persistent, draggable ATS/résumé-match widget — visible on every page, not just a per-job
 * drawer. Shows whichever job JobDrawer last opened (via useFocusStore) and the résumé the
 * recommendation engine ranks highest for it, with a one-paragraph synopsis of why.
 *
 * Mounted once at the app shell (AppLayout), alongside CommandPalette/InterventionModal —
 * the same pattern, not a new one.
 */
export default function FloatingAtsWidget() {
  const focusedJobId = useFocusStore((s) => s.focusedJobId);
  const focusedJobTitle = useFocusStore((s) => s.focusedJobTitle);
  const { data: recommendation, isLoading } = useResumeRecommendation(focusedJobId ?? undefined);
  const navigate = useNavigate();

  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [position, setPosition] = useState<Position>(loadPosition);
  const dragState = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0');
    } catch {
      // Best-effort persistence only — the widget still works within this session either way.
    }
  }, [collapsed]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragState.current) return;
      const dx = e.clientX - dragState.current.startX;
      const dy = e.clientY - dragState.current.startY;
      const next = {
        x: Math.min(Math.max(0, dragState.current.originX + dx), window.innerWidth - 60),
        y: Math.min(Math.max(0, dragState.current.originY + dy), window.innerHeight - 40),
      };
      setPosition(next);
    };
    const onUp = () => {
      if (!dragState.current) return;
      dragState.current = null;
      setDragging(false);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(position));
      } catch {
        // Best-effort — dragging still works for the rest of this session without it.
      }
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    // position is read only inside onUp via closure-at-call-time; re-subscribing per-move
    // would fight the drag, so it is intentionally omitted from the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startDrag = (e: React.MouseEvent) => {
    dragState.current = {
      startX: e.clientX, startY: e.clientY, originX: position.x, originY: position.y,
    };
    setDragging(true);
  };

  if (!focusedJobId) return null;

  const top = recommendation?.rankings[0];
  const score = top ? Math.round(top.score.overall_score * 100) : null;

  return (
    <div
      role="complementary"
      aria-label="ATS résumé match"
      style={{
        position: 'fixed', left: position.x, top: position.y, zIndex: 90,
        width: collapsed ? 'auto' : 300,
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-pop)',
        overflow: 'hidden', userSelect: dragging ? 'none' : 'auto',
        cursor: dragging ? 'grabbing' : 'default',
      }}
    >
      <div
        onMouseDown={startDrag}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '9px 10px',
          background: 'var(--surface-2)', borderBottom: collapsed ? 'none' : '1px solid var(--border)',
          cursor: 'grab',
        }}
      >
        <Icon name="target" size={14} />
        <span
          style={{
            flex: '1 1 auto', minWidth: 0, font: '700 11.5px/1 var(--font)',
            textTransform: 'uppercase', letterSpacing: '.04em', color: 'var(--text-2)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
          title={focusedJobTitle}
        >
          {collapsed ? (score !== null ? `${score}% match` : 'ATS match') : focusedJobTitle || 'ATS match'}
        </span>
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? 'Expand' : 'Collapse'}
          style={{
            flex: '0 0 auto', width: 22, height: 22, display: 'grid', placeItems: 'center',
            background: 'transparent', border: 'none', color: 'var(--text-3)', cursor: 'pointer',
            borderRadius: 'var(--r-sm)', font: '700 10px/1 var(--font)',
          }}
        >
          {collapsed ? '▲' : '▾'}
        </button>
      </div>

      {!collapsed && (
        <div style={{ padding: 14 }}>
          {isLoading ? (
            <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
              Scoring your résumés against this role…
            </p>
          ) : !recommendation || recommendation.rankings.length === 0 ? (
            <p style={{ margin: 0, font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
              {recommendation?.synopsis || 'No résumés to score yet.'}
            </p>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
                <span style={{ font: '800 22px/1 var(--font)', color: 'var(--accent)' }}>
                  {score}%
                </span>
                <span
                  style={{
                    font: '600 12px/1.3 var(--font)', color: 'var(--text)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}
                  title={top?.resume_name}
                >
                  {top?.resume_name}
                </span>
              </div>
              <p style={{ margin: '0 0 12px', font: '500 12px/1.5 var(--font)', color: 'var(--text-2)' }}>
                {recommendation.synopsis}
              </p>
              <button
                type="button"
                onClick={() => navigate('/jobs')}
                style={{
                  width: '100%', height: 32, borderRadius: 'var(--r-md)',
                  background: 'transparent', border: '1px solid var(--border-2)',
                  color: 'var(--text-2)', font: '700 11.5px/1 var(--font)', cursor: 'pointer',
                }}
              >
                View full analysis
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
