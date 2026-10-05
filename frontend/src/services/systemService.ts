import api from '@/services/api';
import type { SystemStatusResponse } from '@/types/system';

/** Connection status of every dependency (database, LLM gateway, Gmail, job boards, agent). */
export async function getSystemStatus(): Promise<SystemStatusResponse> {
  const { data } = await api.get<SystemStatusResponse>('/system/status');
  return data;
}
