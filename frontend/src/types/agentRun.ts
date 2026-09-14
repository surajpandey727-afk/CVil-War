/** The five named agents (`app.models.enums.AgentName`), in the fixed hand-off order the
 *  graph renders them: sourcing, then eligibility, then scoring, then applying, then tracking. */
export type AgentName = 'discovery' | 'eligibility' | 'scoring' | 'application' | 'tracking';

export type AgentRunStatus = 'running' | 'done' | 'error' | 'needs_review';

export interface AgentRunItem {
  id: string;
  agent_name: AgentName;
  status: AgentRunStatus;
  started_at: string;
  finished_at: string | null;
  input_summary: string | null;
  output_summary: string | null;
  error: string | null;
  linked_entity_type: string | null;
  linked_entity_id: string | null;
}

export interface AgentNodeState {
  agent_name: AgentName;
  status: AgentRunStatus | null;
  last_run: AgentRunItem | null;
}

export interface AgentRunListResponse {
  items: AgentRunItem[];
  total: number;
  nodes: AgentNodeState[];
}

export interface AgentRunFilters {
  agent_name?: AgentName;
  status?: AgentRunStatus;
  linked_entity_type?: string;
  linked_entity_id?: string;
  page?: number;
  page_size?: number;
}
