/** One agent on the AI Agents page: status, last run, counts and what you can do with it. */
import { Link } from 'react-router-dom';

import Icon, { type IconName } from '@/components/ui/Icon';
import ConfirmCard from '@/components/assistant/ConfirmCard';
import { relativeTime } from '@/lib/status';
import type { AgentCard, AgentStatus, PendingAction } from '@/types/assistant';

const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: 'Idle',
  running: 'Running',
  needs_attention: 'Needs attention',
  off: 'Off',
};

const ICON: Record<string, IconName> = {
  discovery: 'search',
  eligibility: 'shield',
  scoring: 'gauge',
  resume: 'file',
  application: 'inbox',
  tracking: 'mail',
  assistant: 'sparkle',
};

/** relativeTime gives "5m" / "3h" for recent times; make them read as "5m ago". */
function ago(iso: string): string {
  const rel = relativeTime(iso);
  return /\d[mh]$/.test(rel) ? `${rel} ago` : rel;
}

interface Props {
  agent: AgentCard;
  /** A proposed action for this agent, awaiting confirmation. */
  pending: PendingAction | null;
  preparing: boolean;
  notice: string | null;
  onPrepare: (action: string) => void;
  onDismiss: () => void;
}

export default function AgentTile({ agent, pending, preparing, notice, onPrepare, onDismiss }: Props) {
  const headingId = `ag-${agent.key}`;
  const run = agent.last_run;
  return (
    <article className="ag-card" aria-labelledby={headingId} data-status={agent.status}>
      <header className="ag-card-head">
        <span className="ag-icon" aria-hidden="true"><Icon name={ICON[agent.key] ?? 'cpu'} size={17} /></span>
        <h2 id={headingId}>{agent.name}</h2>
        <span className="ag-status" data-status={agent.status}>
          <span className="ag-dot" aria-hidden="true" />
          {STATUS_LABEL[agent.status]}
        </span>
      </header>

      <p className="ag-desc">{agent.description}</p>
      <p className="ag-state">{agent.status_text}</p>

      {agent.counts.length > 0 && (
        <dl className="ag-counts">
          {agent.counts.map((c) => (
            <div key={c.label} className="ag-count">
              <dt>{c.label}</dt>
              <dd>{c.value.toLocaleString('en-GB')}</dd>
            </div>
          ))}
        </dl>
      )}

      <p className="ag-run">
        <Icon name="clock" size={12} style={{ display: 'inline-block', verticalAlign: '-2px', marginRight: 5 }} />
        {!agent.tracks_runs
          ? 'Runs on request (no run log)'
          : run
            ? `Last run ${ago(run.started_at)} · ${run.status.replace('_', ' ')}${run.summary ? ` · ${run.summary}` : ''}`
            : 'No runs recorded yet'}
      </p>
      {run?.error && <p className="ag-error">{run.error}</p>}

      {pending && (
        <ConfirmCard
          key={pending.token}
          pending={pending}
          onResolved={(state) => { if (state === 'cancelled') onDismiss(); }}
        />
      )}
      {notice && <p className="ag-notice" role="status">{notice}</p>}

      <div className="ag-actions">
        <Link className="ag-link ag-link-primary" to={agent.section.to ?? '/'}>
          Open {agent.section.label} <Icon name="chevR" size={13} />
        </Link>
        {agent.actions.map((a) =>
          a.kind === 'confirm' && a.action ? (
            <button
              key={a.label}
              type="button"
              className="ag-link"
              onClick={() => onPrepare(a.action as string)}
              disabled={preparing || pending !== null}
            >
              {preparing ? <span className="as-spin" aria-hidden="true" /> : <Icon name="play" size={12} />}
              {a.label}
            </button>
          ) : (
            <Link key={a.label} className="ag-link" to={a.to ?? '/'}>{a.label}</Link>
          ),
        )}
      </div>
    </article>
  );
}
