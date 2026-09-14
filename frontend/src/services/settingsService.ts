import api from './api';
import type { AICatalogue, AIUsagePeriod, AIUsageReport } from '@/types/aiSettings';
import type {
  ConnectAttempt,
  PlatformsResponse,
  PlatformTestResponse,
} from '@/types/platforms';
import type {
  AutomationSettings,
  BYOLLMKeyStatus,
  BYOLLMKeyUpdate,
  LLMProviderStatus,
  PolicyCatalogue,
  PolicyPreview,
  Settings,
  SettingsUpdate,
} from '@/types/settings';

/** Get the current user settings. */
export async function getSettings(): Promise<Settings> {
  const { data } = await api.get<Settings>('/settings/');
  return data;
}

/** Update user settings. Only provided fields are changed. */
export async function updateSettings(update: SettingsUpdate): Promise<Settings> {
  const { data } = await api.put<Settings>('/settings/', update);
  return data;
}

/** List configured LLM providers and their status. */
export async function getLLMProviders(): Promise<LLMProviderStatus[]> {
  const { data } = await api.get<LLMProviderStatus[]>('/settings/llm-providers');
  return data;
}

/** Which providers have a BYO key stored for this account. Never returns the key itself. */
export async function getBYOLLMKeys(): Promise<BYOLLMKeyStatus[]> {
  const { data } = await api.get<BYOLLMKeyStatus[]>('/settings/llm-key');
  return data;
}

/** Save this account's own API key for one provider. */
export async function saveBYOLLMKey(update: BYOLLMKeyUpdate): Promise<BYOLLMKeyStatus> {
  const { data } = await api.put<BYOLLMKeyStatus>('/settings/llm-key', update);
  return data;
}

/** Remove a stored BYO key. */
export async function deleteBYOLLMKey(provider: string): Promise<void> {
  await api.delete(`/settings/llm-key/${encodeURIComponent(provider)}`);
}

/**
 * The automation policy catalogue: every clause, its control spec, and the current value.
 *
 * The automation screen renders itself from this rather than hard-coding controls, so a rule
 * added to the backend shows up with its bounds and its rationale attached.
 */
export async function getPolicyCatalogue(): Promise<PolicyCatalogue> {
  const { data } = await api.get<PolicyCatalogue>('/settings/automation-policy');
  return data;
}

/** Dry-run an unsaved policy against everything currently queued. Persists nothing. */
export async function previewPolicy(candidate: AutomationSettings): Promise<PolicyPreview> {
  const { data } = await api.post<PolicyPreview>('/settings/automation-policy/preview', candidate);
  return data;
}

/**
 * Providers and models the configured gateway can actually route to.
 *
 * Discovered live. The list this replaced was five hard-coded providers with model names the
 * gateway does not offer; the real answer for this deployment is 648 models across 16.
 */
export async function getAICatalogue(refresh = false): Promise<AICatalogue> {
  const { data } = await api.get<AICatalogue>('/settings/ai/catalogue', {
    params: refresh ? { refresh: true } : undefined,
  });
  return data;
}

/** Recorded token usage and cost, summed from calls this account actually made. */
export async function getAIUsage(period: AIUsagePeriod): Promise<AIUsageReport> {
  const { data } = await api.get<AIUsageReport>('/settings/ai/usage', { params: { period } });
  return data;
}

/** Every job source with this user's enablement and connection state. */
export async function getPlatforms(): Promise<PlatformsResponse> {
  const { data } = await api.get<PlatformsResponse>('/settings/platforms');
  return data;
}

/** Disconnect a stored platform session. */
export async function disconnectPlatform(platform: string): Promise<void> {
  await api.delete(`/platform-sessions/${platform}`);
}

/** Open a login window so the operator can sign in to a platform themselves. */
export async function startConnect(platform: string): Promise<ConnectAttempt> {
  const { data } = await api.post<ConnectAttempt>('/platform-sessions/connect', { platform });
  return data;
}

/** Poll an in-flight login capture. */
export async function getConnectAttempt(id: string): Promise<ConnectAttempt> {
  const { data } = await api.get<ConnectAttempt>(`/platform-sessions/connect/${id}`);
  return data;
}

/** Abandon a login capture and close its window. */
export async function cancelConnect(id: string): Promise<ConnectAttempt> {
  const { data } = await api.delete<ConnectAttempt>(`/platform-sessions/connect/${id}`);
  return data;
}

/** Probe sources for real. An empty `keys` tests everything with a working adapter. */
export async function testPlatforms(keys: string[] = []): Promise<PlatformTestResponse> {
  const { data } = await api.post<PlatformTestResponse>('/settings/platforms/test', { keys });
  return data;
}

/** Enable or disable many sources in one write. */
export async function bulkUpdatePlatforms(
  keys: string[],
  enabled: boolean,
): Promise<PlatformsResponse> {
  const { data } = await api.put<PlatformsResponse>('/settings/platforms/bulk', { keys, enabled });
  return data;
}
