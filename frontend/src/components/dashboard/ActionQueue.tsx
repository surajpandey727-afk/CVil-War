import { useNavigate } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import { useActionQueue } from '@/hooks/useCommandCentre';
import { ACTION_META, PRIORITY_COLOR, type ActionItem } from '@/types/commandCentre';

/**
 * The primary operational surface: everything needing the user, most consequential first.
 *
 * Three things this deliberately does, each because the alternative failed a real need:
 *
 * 1. **Shows the reason verbatim.** "Assessment due in 3 hours" rather than a bare priority
 *    badge. A ranking the user cannot second-guess is one they stop trusting.
 * 2. **Routes to the exact thing to do**, using the `target` the backend supplies, so an
 *    action is one click rather than a page they then navigate onward from.
 * 3. **Distinguishes an empty queue from a missing one.** "Nothing needs you" is a genuine,
 *    good state; showing it while the request is still in flight, or failing, would be a lie.
 */

/** Where each `target` resolves to. Kept beside the queue so a new action is one line. */
const ROUTE_FOR_TARGET: Record<string, (item: ActionItem) => string> = {
  assessment: (i) => `/applications/${i.application_id}`,
  interview: (i) => `/applications/${i.application_id}`,
  connection: () => '/sources',
  resume: (i) => `/applications/${i.application_id}`,
  documents: () => '/resumes',
  review: (i) => `/applications/${i.application_id}`,
  verify: (i) => `/applications/${i.application_id}`,
  follow_up: (i) => `/applications/${i.application_id}`,
  messages: (i) => `/applications/${i.application_id}`,
  profile: () => '/settings',
  application: (i) => `/applications/${i.application_id}`,
};

function dueLabel(due: string | null): string | null {
  if (!due) return null;
  const ms = new Date(due).getTime() - Date.now();
  if (Number.isNaN(ms)) return null;
  const hours = ms / 3_600_000;
  if (hours < 0) return 'Overdue';
  if (hours < 1) return `${Math.round(hours * 60)}m left`;
  if (hours < 48) return `${Math.round(hours)}h left`;
  return `${Math.round(hours / 24)}d left`;
}

export default function ActionQueue({ limit }: { limit?: number }) {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useActionQueue();

  const card: React.CSSProperties = {
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)',
  };

  if (isLoading) {
    return (
      <div style={{ ...card, padding: 18 }}>
        <div style={{ font: '600 12px/1 var(--mono)', color: 'var(--text-4)' }}>
          Loading what needs you…
        </div>
      </div>
    );
  }

  if (isError) {
    // Never render this as "nothing to do" — an unreachable queue and an empty queue mean
    // opposite things, and conflating them hides work the user must not miss.
    return (
      <div style={{ ...card, padding: 18, borderColor: 'var(--rejected)' }}>
        <div style={{ font: '700 13px/1.3 var(--font)', color: 'var(--rejected)' }}>
          Could not load your action queue
        </div>
        <div style={{ font: '500 12px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 6 }}>
          This is not the same as having nothing to do. Retry, or check the API is running.
        </div>
      </div>
    );
  }

  const items = limit ? (data?.items ?? []).slice(0, limit) : (data?.items ?? []);
  const counts = data?.by_priority ?? {};

  return (
    <div style={{ ...card, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <span style={{ font: '800 13px/1 var(--font)', letterSpacing: '-.01em' }}>Needs your attention</span>
          {(data?.total ?? 0) > 0 && (
            <span style={{ font: '700 10px/1 var(--mono)', padding: '3px 7px', borderRadius: 999, background: 'var(--accent-soft)', color: 'var(--accent)' }}>
              {data?.total}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, font: '600 10px/1 var(--mono)', color: 'var(--text-4)' }}>
          {(['high', 'medium', 'low'] as const).map((p) =>
            counts[p] ? (
              <span key={p} style={{ color: PRIORITY_COLOR[p] }}>
                {counts[p]} {p}
              </span>
            ) : null,
          )}
        </div>
      </div>

      {items.length === 0 ? (
        <div style={{ padding: '26px 16px', textAlign: 'center' }}>
          <div style={{ font: '700 13px/1.3 var(--font)', color: 'var(--text-2)' }}>
            Nothing needs you right now
          </div>
          <div style={{ font: '500 12px/1.4 var(--font)', color: 'var(--text-4)', marginTop: 5 }}>
            No deadlines, blocked applications or overdue follow-ups.
          </div>
        </div>
      ) : (
        <div>
          {items.map((item) => {
            const meta = ACTION_META[item.action];
            const due = dueLabel(item.due_at);
            const to = (ROUTE_FOR_TARGET[item.target] ?? ROUTE_FOR_TARGET['application']!)(item);
            return (
              <button
                key={item.application_id}
                onClick={() => navigate(to)}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 12,
                  padding: '12px 16px', background: 'none', border: 0,
                  borderTop: '1px solid var(--border)', cursor: 'pointer', textAlign: 'left',
                }}
              >
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: PRIORITY_COLOR[item.priority], flex: '0 0 auto' }} />
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'block', font: '700 12.5px/1.3 var(--font)', color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {meta.label} · {item.title}
                  </span>
                  <span style={{ display: 'block', font: '500 11.5px/1.4 var(--font)', color: 'var(--text-3)', marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {item.company ? `${item.company} — ` : ''}{item.reason}
                  </span>
                </span>
                {due && (
                  <span style={{ font: '700 10px/1 var(--mono)', color: PRIORITY_COLOR[item.priority], flex: '0 0 auto' }}>
                    {due}
                  </span>
                )}
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, font: '700 11px/1 var(--font)', color: 'var(--accent)', flex: '0 0 auto' }}>
                  {meta.cta} <Icon name="chevR" size={13} />
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
