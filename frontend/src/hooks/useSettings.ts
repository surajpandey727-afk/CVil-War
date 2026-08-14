import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as settingsService from '@/services/settingsService';
import type { AIUsagePeriod } from '@/types/aiSettings';
import type { AutomationSettings, SettingsUpdate } from '@/types/settings';

const SETTINGS_KEY = ['settings'] as const;

/** Fetch current user settings. */
export function useSettings() {
  return useQuery({
    queryKey: [...SETTINGS_KEY, 'current'],
    queryFn: () => settingsService.getSettings(),
  });
}

/** Update user settings. */
export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (update: SettingsUpdate) => settingsService.updateSettings(update),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SETTINGS_KEY });
    },
  });
}

/** Fetch LLM provider statuses. */
export function useLLMProviders() {
  return useQuery({
    queryKey: [...SETTINGS_KEY, 'llm-providers'],
    queryFn: () => settingsService.getLLMProviders(),
  });
}

/** Fetch the automation policy catalogue that drives the automation screen. */
export function usePolicyCatalogue() {
  return useQuery({
    queryKey: [...SETTINGS_KEY, 'automation-policy'],
    queryFn: () => settingsService.getPolicyCatalogue(),
  });
}

/**
 * Dry-run a candidate policy. A mutation rather than a query because it is an explicit
 * action with a body: previewing on every keystroke would put a burst of multi-query
 * evaluations behind a single slider drag.
 */
export function usePolicyPreview() {
  return useMutation({
    mutationFn: (candidate: AutomationSettings) => settingsService.previewPolicy(candidate),
  });
}

/** Providers/models the gateway offers. `refresh` re-queries instead of using the cache. */
export function useAICatalogue(refresh = false) {
  return useQuery({
    queryKey: [...SETTINGS_KEY, 'ai-catalogue'],
    queryFn: () => settingsService.getAICatalogue(refresh),
  });
}

/** Recorded LLM usage for one period. */
export function useAIUsage(period: AIUsagePeriod) {
  return useQuery({
    queryKey: [...SETTINGS_KEY, 'ai-usage', period],
    queryFn: () => settingsService.getAIUsage(period),
  });
}

/** Job sources with connection state, from the same registry the Sources screen reads. */
export function usePlatforms() {
  return useQuery({
    queryKey: [...SETTINGS_KEY, 'platforms'],
    queryFn: () => settingsService.getPlatforms(),
  });
}

/** Disconnect a platform. Invalidates settings and sources so both screens agree. */
export function useDisconnectPlatform() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (platform: string) => settingsService.disconnectPlatform(platform),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SETTINGS_KEY });
      void queryClient.invalidateQueries({ queryKey: ['sources'] });
    },
  });
}
