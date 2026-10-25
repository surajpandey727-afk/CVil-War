/** AI Agents — every agent on the platform, what it's doing, and what you can ask of it.
 *
 *  Status is honest by construction: it comes from each agent's own run log plus the
 *  configuration it depends on, so an agent that can't run here says so instead of looking
 *  idle. Actions that change something (e.g. running discovery) go through the same
 *  confirm-before-acting flow as the Assistant. */
import { useState } from 'react';
import { Link } from 'react-router-dom';

import Icon from '@/components/ui/Icon';
import AgentTile from '@/components/assistant/AgentTile';
import { useAgentsRoster, usePrepareAction } from '@/hooks/useAssistant';
import { apiErrorMessage } from '@/lib/apiError';
import type { PendingAction } from '@/types/assistant';
import '@/styles/assistant.css';
import '@/styles/agents.css';

export default function AgentsPage() {
  const { data, isLoading, isError, error, refetch, isFetching } = useAgentsRoster();
  const prepare = usePrepareAction();
  const [pending, setPending] = useState<Record<string, PendingAction>>({});
  const [notice, setNotice] = useState<Record<string, string>>({});
  const [preparingKey, setPreparingKey] = useState<string | null>(null);

  const onPrepare = (agentKey: string, action: string) => {
    setPreparingKey(agentKey);
    setNotice((n) => ({ ...n, [agentKey]: '' }));
    prepare.mutate(action, {
      onSuccess: (res) => {
        if (res.ok && res.pending) setPending((p) => ({ ...p, [agentKey]: res.pending as PendingAction }));
        else setNotice((n) => ({ ...n, [agentKey]: res.message || 'That action is not available.' }));
      },
      onError: (err) => setNotice((n) => ({ ...n, [agentKey]: apiErrorMessage(err, 'Could not prepare that action.') })),
      onSettled: () => setPreparingKey(null),
    });
  };

  const dismiss = (agentKey: string) =>
    setPending((p) => {
      const next = { ...p };
      delete next[agentKey];
      return next;
    });

  const agents = data?.agents ?? [];
  const attention = agents.filter((a) => a.status === 'needs_attention').length;

  return (
    <div className="as ag">
      <header className="as-head">
        <div>
          <h1>AI Agents</h1>
          <p>
            The agents that find, check, score and apply for UK roles on your behalf. Ask the{' '}
            <Link to="/assistant">Assistant</Link> to coordinate them, or act on one directly.
          </p>
        </div>
        <button type="button" className="as-btn as-btn-quiet" onClick={() => void refetch()} disabled={isFetching}>
          <Icon name="refresh" size={13} /> Refresh
        </button>
      </header>

      <div className="as-sr" aria-live="polite">
        {data ? `${agents.length} agents, ${attention} need attention.` : ''}
      </div>

      {isLoading ? (
        <div className="as-panel as-loading"><span className="as-spin" aria-hidden="true" /> Loading agents…</div>
      ) : isError ? (
        <div className="as-alert" role="alert">
          <Icon name="alert" size={15} />
          <span className="as-alert-text">{apiErrorMessage(error, 'Could not load the agents.')}</span>
        </div>
      ) : (
        <>
          {data && !data.assistant_available && (
            <p className="ag-banner">
              <Icon name="alert" size={14} /> The Assistant is off on this deployment (no Anthropic API key). The other agents still run.
            </p>
          )}
          <div className="ag-grid">
            {agents.map((a) => (
              <AgentTile
                key={a.key}
                agent={a}
                pending={pending[a.key] ?? null}
                preparing={preparingKey === a.key}
                notice={notice[a.key] || null}
                onPrepare={(action) => onPrepare(a.key, action)}
                onDismiss={() => dismiss(a.key)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
