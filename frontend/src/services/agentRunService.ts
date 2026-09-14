import api from './api';
import type { AgentRunFilters, AgentRunListResponse } from '@/types/agentRun';

/** Live per-agent node state plus filtered run history — backs the Agent Ops graph view. */
export async function listAgentRuns(filters: AgentRunFilters = {}): Promise<AgentRunListResponse> {
  const params: Record<string, string | number> = {};
  if (filters.agent_name) params['agent_name'] = filters.agent_name;
  if (filters.status) params['status'] = filters.status;
  if (filters.linked_entity_type) params['linked_entity_type'] = filters.linked_entity_type;
  if (filters.linked_entity_id) params['linked_entity_id'] = filters.linked_entity_id;
  params['page'] = filters.page ?? 1;
  params['page_size'] = filters.page_size ?? 30;
  const { data } = await api.get<AgentRunListResponse>('/agent-runs/', { params });
  return data;
}
