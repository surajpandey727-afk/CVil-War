import { useQuery } from '@tanstack/react-query';

import * as agentRunService from '@/services/agentRunService';
import type { AgentRunFilters } from '@/types/agentRun';

export const AGENT_RUNS_KEY = ['agent-runs'] as const;

/**
 * Live agent-node state plus filtered run history.
 *
 * No polling interval here — the WS `agent_state_changed` event (wired in
 * `useApplicationEvents`) invalidates this query the moment any agent's status actually
 * changes, so the graph updates live without hammering the endpoint on a timer. A short
 * `staleTime` just avoids a redundant refetch if the page remounts a moment after a WS event
 * already refreshed it.
 */
export function useAgentRuns(filters: AgentRunFilters = {}) {
  return useQuery({
    queryKey: [...AGENT_RUNS_KEY, filters],
    queryFn: () => agentRunService.listAgentRuns(filters),
    staleTime: 5_000,
  });
}
