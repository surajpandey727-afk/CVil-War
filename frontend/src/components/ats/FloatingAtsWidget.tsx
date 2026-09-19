import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import { useResumeRecommendation } from '@/hooks/useJobs';
import { useAiAtsReview } from '@/hooks/useResumes';
import { useFocusStore } from '@/store/useFocusStore';
import { useAppStore } from '@/store/useAppStore';

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
  const notify = useAppStore((s) => s.showNotification);
  const aiReview = useAiAtsReview();

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

  // A stale AI review from the previously-focused job must not linger under a new one's
  // heading — the mutation's own `.data` has no natural reset point tied to focus changes.
  useEffect(() => {
    aiReview.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusedJobId]);

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
        width: collapsed ? 'auto' : 320,
        maxHeight: collapsed ? 'auto' : '80vh', overflowY: collapsed ? 'visible' : 'auto',
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
              <p style={{ margin: '0 0 10px', font: '500 12px/1.5 var(--font)', color: 'var(--text-2)' }}>
                {recommendation.synopsis}
              </p>

              {(top?.score.missing_skills.length || top?.score.suggestions.length) ? (
                <div style={{ marginBottom: 12 }}>
                  {top.score.missing_skills.length > 0 && (
                    <div style={{ marginBottom: top.score.suggestions.length ? 8 : 0 }}>
                      <div style={{ font: '700 10px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 5 }}>
                        Missing skills
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                        {top.score.missing_skills.slice(0, 6).map((s) => (
                          <span key={s} style={{ padding: '2px 7px', borderRadius: 999, background: 'var(--rejected-soft)', color: 'var(--rejected)', font: '600 10.5px/1.4 var(--font)' }}>
                            {s}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {top.score.suggestions.length > 0 && (
                    <ul style={{ margin: 0, padding: '0 0 0 16px', font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
                      {top.score.suggestions.slice(0, 3).map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                  )}
                </div>
              ) : null}

              <button
                type="button"
                onClick={() => navigate('/jobs')}
                style={{
                  width: '100%', height: 32, marginBottom: 8, borderRadius: 'var(--r-md)',
                  background: 'transparent', border: '1px solid var(--border-2)',
                  color: 'var(--text-2)', font: '700 11.5px/1 var(--font)', cursor: 'pointer',
                }}
              >
                View full analysis
              </button>

              {top && (
                <AiReviewSection
                  resumeId={top.resume_id}
                  jobId={focusedJobId!}
                  aiReview={aiReview}
                  notify={notify}
                />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function AiReviewSection({
  resumeId, jobId, aiReview, notify,
}: {
  resumeId: string;
  jobId: string;
  aiReview: ReturnType<typeof useAiAtsReview>;
  notify: (message: string, severity?: 'info' | 'success' | 'warning' | 'error') => void;
}) {
  const run = () =>
    aiReview.mutate(
      { resumeId, jobId },
      {
        onError: () => notify('Could not reach the AI reviewer', 'error'),
        onSuccess: (result) => {
          if (!result.available) notify(result.detail || 'The AI reviewer is unavailable right now', 'warning');
        },
      },
    );

  if (!aiReview.data) {
    return (
      <button
        type="button"
        onClick={run}
        disabled={aiReview.isPending}
        style={{
          width: '100%', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          height: 32, borderRadius: 'var(--r-md)', background: 'var(--accent-soft)',
          border: '1px solid var(--accent-line)', color: 'var(--accent)',
          font: '700 11.5px/1 var(--font)', cursor: aiReview.isPending ? 'wait' : 'pointer',
        }}
      >
        <Icon name="sparkle" size={13} />
        {aiReview.isPending ? 'Reviewing…' : 'Get AI ATS review'}
      </button>
    );
  }

  const { review, available, detail } = aiReview.data;
  if (!available || !review) {
    return (
      <p style={{ margin: 0, font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
        {detail || 'The AI reviewer is unavailable right now.'}
      </p>
    );
  }

  return (
    <div style={{ borderTop: '1px solid var(--border)', paddingTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 6 }}>
        <span style={{ font: '800 15px/1 var(--font)', color: 'var(--accent)' }}>
          {Math.round(review.semantic_score * 100)}%
        </span>
        <span style={{ font: '700 10px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>
          AI semantic fit
        </span>
      </div>
      <p style={{ margin: '0 0 8px', font: '500 11.5px/1.5 var(--font)', color: 'var(--text-2)' }}>
        {review.verdict}
      </p>

      {review.contextually_satisfied_skills.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ font: '700 10px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4 }}>
            Covered under different wording
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {review.contextually_satisfied_skills.map((s) => (
              <span key={s} style={{ padding: '2px 7px', borderRadius: 999, background: 'var(--applied-soft)', color: 'var(--applied)', font: '600 10.5px/1.4 var(--font)' }}>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {review.still_missing_skills.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ font: '700 10px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4 }}>
            Genuinely missing
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {review.still_missing_skills.map((s) => (
              <span key={s} style={{ padding: '2px 7px', borderRadius: 999, background: 'var(--rejected-soft)', color: 'var(--rejected)', font: '600 10.5px/1.4 var(--font)' }}>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {(review.recency_note || review.seniority_note) && (
        <p style={{ margin: '0 0 8px', font: '500 11px/1.5 var(--font)', color: 'var(--text-3)' }}>
          {[review.recency_note, review.seniority_note].filter(Boolean).join(' ')}
        </p>
      )}

      {review.weak_bullets.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ font: '700 10px/1 var(--font)', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>
            Weak bullets
          </div>
          {review.weak_bullets.map((b, i) => (
            <div key={i} style={{ padding: 8, borderRadius: 'var(--r-sm)', background: 'var(--surface-2)' }}>
              <div style={{ font: '500 11px/1.4 var(--font)', color: 'var(--text-3)', textDecoration: 'line-through', marginBottom: 4 }}>
                {b.original}
              </div>
              <div style={{ font: '600 11px/1.4 var(--font)', color: 'var(--text)' }}>
                {b.rewrite}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
