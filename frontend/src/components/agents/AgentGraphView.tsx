import { useState } from 'react';

import Icon, { type IconName } from '@/components/ui/Icon';
import { useAgentRuns } from '@/hooks/useAgentRuns';
import { relativeTime } from '@/lib/status';
import type { AgentName, AgentRunStatus } from '@/types/agentRun';

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)', boxShadow: 'var(--shadow-1)', padding: 18,
};

/** Fixed hand-off order the graph renders left to right — the one real sequence a job
 *  moves through, not an arbitrary list. Discovery and Application each have their own
 *  trigger (a cron tick; an apply-worker job) rather than a graph edge into them, which is
 *  why they are still drawn here but not claimed to feed one another directly. */
const AGENT_ORDER: { key: AgentName; label: string; icon: IconName; blurb: string }[] = [
  { key: 'discovery', label: 'Discovery', icon: 'search', blurb: 'Sources listings from every enabled portal' },
  { key: 'eligibility', label: 'Eligibility', icon: 'shield', blurb: 'Visa-sponsorship classification' },
  { key: 'scoring', label: 'Scoring', icon: 'target', blurb: 'Which résumé fits, and why' },
  { key: 'application', label: 'Application', icon: 'cursor', blurb: 'Submits through the policy gate' },
  { key: 'tracking', label: 'Tracking', icon: 'mail', blurb: 'Recruiter contact + reply detection' },
];

const STATUS_STYLE: Record<AgentRunStatus, { color: string; soft: string; label: string; pulse?: boolean }> = {
  running: { color: 'var(--accent)', soft: 'var(--accent-soft)', label: 'Running', pulse: true },
  done: { color: 'var(--offer)', soft: 'var(--offer-soft)', label: 'Done' },
  error: { color: 'var(--rejected)', soft: 'var(--rejected-soft)', label: 'Error' },
  needs_review: { color: 'var(--pending)', soft: 'var(--surface-3)', label: 'Needs review' },
};

const IDLE_STYLE: { color: string; soft: string; label: string; pulse?: boolean } = {
  color: 'var(--text-4)', soft: 'var(--surface-2)', label: 'Idle',
};

/**
 * The multi-agent visualization: one node per named agent, coloured by its own most recent
 * run, plus a filterable log underneath. Every node's status is a fact already written by
 * `core.orchestration.recorder.record_agent_run` at the point that agent actually ran — this
 * component computes nothing, it only renders `GET /api/v1/agent-runs`.
 */
export default function AgentGraphView() {
  const [agentFilter, setAgentFilter] = useState<AgentName | null>(null);
  const [statusFilter, setStatusFilter] = useState<AgentRunStatus | null>(null);

  const { data, isLoading, isError, refetch } = useAgentRuns({
    agent_name: agentFilter ?? undefined,
    status: statusFilter ?? undefined,
  });

  const nodeByAgent = new Map((data?.nodes ?? []).map((n) => [n.agent_name, n]));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <section style={card}>
        <div style={{ font: '700 13.5px/1 var(--font)', marginBottom: 4 }}>Live agent graph</div>
        <p style={{ margin: '0 0 18px', font: '500 12px/1.5 var(--font)', color: 'var(--text-3)' }}>
          Each node is a single-responsibility agent. Colour reflects its own most recent run —
          this is not a simulation, it updates the moment a real run starts or finishes.
        </p>
        <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, overflowX: 'auto', paddingBottom: 4 }}>
          {AGENT_ORDER.map((agent, i) => {
            const node = nodeByAgent.get(agent.key);
            const style = node?.status ? STATUS_STYLE[node.status] : IDLE_STYLE;
            return (
              <div key={agent.key} style={{ display: 'flex', alignItems: 'center', flex: '0 0 auto' }}>
                <button
                  onClick={() => setAgentFilter((cur) => (cur === agent.key ? null : agent.key))}
                  title={agent.blurb}
                  style={{
                    width: 148, minHeight: 116, padding: '14px 12px', borderRadius: 'var(--r-lg)',
                    border: `1.5px solid ${agentFilter === agent.key ? style.color : 'var(--border)'}`,
                    background: style.soft, cursor: 'pointer', textAlign: 'left',
                    display: 'flex', flexDirection: 'column', gap: 8,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{
                      width: 30, height: 30, borderRadius: 9, display: 'grid', placeItems: 'center',
                      background: 'var(--surface)', color: style.color, position: 'relative',
                    }}>
                      <Icon name={agent.icon} size={16} />
                      {style.pulse && (
                        <span style={{
                          position: 'absolute', top: -3, right: -3, width: 8, height: 8, borderRadius: '50%',
                          background: style.color, animation: 'aaPulse 1.4s var(--ease-io) infinite',
                        }} />
                      )}
                    </span>
                    <span style={{ font: '700 9.5px/1 var(--mono)', letterSpacing: '.04em', color: style.color, textTransform: 'uppercase' }}>
                      {style.label}
                    </span>
                  </div>
                  <div style={{ font: '700 12.5px/1.2 var(--font)' }}>{agent.label}</div>
                  <div style={{ font: '500 10.5px/1.4 var(--font)', color: 'var(--text-3)' }}>
                    {node?.last_run
                      ? (node.last_run.output_summary || node.last_run.input_summary || '—')
                      : 'Has not run yet'}
                  </div>
                  {node?.last_run && (
                    <div style={{ font: '600 10px/1 var(--mono)', color: 'var(--text-4)', marginTop: 'auto' }}>
                      {relativeTime(node.last_run.finished_at ?? node.last_run.started_at)}
                    </div>
                  )}
                </button>
                {i < AGENT_ORDER.length - 1 && (
                  <div style={{ width: 26, flex: '0 0 auto', display: 'grid', placeItems: 'center', color: 'var(--text-4)' }}>
                    <Icon name="chevR" size={16} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <div style={{ font: '700 13.5px/1 var(--font)' }}>Run log</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginLeft: 'auto' }}>
            {agentFilter && (
              <FilterChip label={AGENT_ORDER.find((a) => a.key === agentFilter)?.label ?? agentFilter} onClear={() => setAgentFilter(null)} />
            )}
            {(['running', 'error', 'needs_review', 'done'] as AgentRunStatus[]).map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter((cur) => (cur === s ? null : s))}
                style={{
                  height: 26, padding: '0 10px', borderRadius: 999, cursor: 'pointer', font: '600 11px/1 var(--font)',
                  border: `1px solid ${statusFilter === s ? STATUS_STYLE[s].color : 'var(--border)'}`,
                  background: statusFilter === s ? STATUS_STYLE[s].soft : 'var(--surface-2)',
                  color: statusFilter === s ? STATUS_STYLE[s].color : 'var(--text-3)',
                }}
              >
                {STATUS_STYLE[s].label}
              </button>
            ))}
          </div>
        </div>

        {isLoading && <Notice>Loading agent history…</Notice>}
        {isError && (
          <Notice>
            Could not load agent history.{' '}
            <button onClick={() => void refetch()} style={{ color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', font: 'inherit', textDecoration: 'underline' }}>
              Try again
            </button>
          </Notice>
        )}
        {!isLoading && !isError && data?.items.length === 0 && (
          <Notice>No agent runs match this filter yet.</Notice>
        )}
        {!isLoading && !isError && data && data.items.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {data.items.map((run) => {
              const style = STATUS_STYLE[run.status];
              return (
                <div key={run.id} style={{
                  display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 12px',
                  borderRadius: 'var(--r-md)', background: 'var(--surface-2)', border: '1px solid var(--border)',
                }}>
                  <span style={{
                    flex: '0 0 auto', marginTop: 2, width: 8, height: 8, borderRadius: '50%', background: style.color,
                  }} />
                  <div style={{ flex: '1 1 auto', minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ font: '700 12px/1.3 var(--font)', textTransform: 'capitalize' }}>{run.agent_name}</span>
                      <span style={{ font: '700 9.5px/1 var(--mono)', color: style.color, textTransform: 'uppercase' }}>{style.label}</span>
                      <span style={{ font: '600 11px/1 var(--mono)', color: 'var(--text-4)', marginLeft: 'auto' }}>
                        {relativeTime(run.started_at)}
                      </span>
                    </div>
                    <div style={{ font: '500 11.5px/1.5 var(--font)', color: 'var(--text-3)', marginTop: 3 }}>
                      {run.error || run.output_summary || run.input_summary || '—'}
                    </div>
                    {run.linked_entity_type && (
                      <div style={{ font: '500 10.5px/1.4 var(--mono)', color: 'var(--text-4)', marginTop: 3 }}>
                        {run.linked_entity_type}: {run.linked_entity_id}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <button
      onClick={onClear}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, height: 26, padding: '0 10px', borderRadius: 999,
        border: '1px solid var(--accent-line)', background: 'var(--accent-soft)', color: 'var(--accent)',
        font: '600 11px/1 var(--font)', cursor: 'pointer',
      }}
    >
      {label}
      <Icon name="x" size={11} />
    </button>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: '20px 0', textAlign: 'center', font: '500 12.5px/1.5 var(--font)', color: 'var(--text-3)' }}>
      {children}
    </div>
  );
}
