import api, { LLM_CALL_TIMEOUT_MS } from './api';
import type {
  AgentRosterResponse,
  ChatMessage,
  ChatResponse,
  ConfirmResponse,
  PrepareResponse,
} from '@/types/assistant';

/** The server keeps at most 20 turns of text-only history. */
export const MAX_HISTORY = 20;

/** One assistant turn — a real multi-step LLM call, so it gets the long timeout. */
export async function sendChat(messages: ChatMessage[]): Promise<ChatResponse> {
  const { data } = await api.post<ChatResponse>(
    '/assistant/chat',
    { messages: messages.slice(-MAX_HISTORY) },
    { timeout: LLM_CALL_TIMEOUT_MS },
  );
  return data;
}

/** Execute an action the assistant (or an agent card) proposed. Discovery can take a minute. */
export async function confirmAction(token: string): Promise<ConfirmResponse> {
  const { data } = await api.post<ConfirmResponse>(
    '/assistant/confirm',
    { token },
    { timeout: LLM_CALL_TIMEOUT_MS },
  );
  return data;
}

export async function prepareAction(action: string): Promise<PrepareResponse> {
  const { data } = await api.post<PrepareResponse>('/assistant/prepare', { action });
  return data;
}

export async function getAgents(): Promise<AgentRosterResponse> {
  const { data } = await api.get<AgentRosterResponse>('/assistant/agents');
  return data;
}
