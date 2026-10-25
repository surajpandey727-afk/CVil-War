/** Assistant chat + AI Agents roster contracts (backend `app/schemas/assistant.py`). */

export type ChatRole = 'user' | 'assistant';

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ToolCallSummary {
  name: string;
  input_summary: string;
  ok: boolean;
  result_summary: string;
}

export interface PendingAction {
  token: string;
  summary: string;
}

export interface ChatResponse {
  reply: string;
  tool_calls: ToolCallSummary[];
  pending: PendingAction[];
  model: string;
}

export interface ConfirmResponse {
  ok: boolean;
  message: string;
}

export interface PrepareResponse {
  ok: boolean;
  pending: PendingAction | null;
  message: string;
}

export type AgentStatus = 'idle' | 'running' | 'needs_attention' | 'off';

export interface AgentLastRun {
  status: string;
  started_at: string;
  finished_at: string | null;
  summary: string | null;
  error: string | null;
}

export interface AgentAction {
  label: string;
  kind: 'link' | 'confirm';
  to: string | null;
  action: string | null;
}

export interface AgentCard {
  key: string;
  name: string;
  description: string;
  status: AgentStatus;
  status_text: string;
  last_run: AgentLastRun | null;
  tracks_runs: boolean;
  counts: { label: string; value: number }[];
  actions: AgentAction[];
  section: AgentAction;
}

export interface AgentRosterResponse {
  agents: AgentCard[];
  assistant_available: boolean;
}
