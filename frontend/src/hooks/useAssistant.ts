import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as assistantService from '@/services/assistantService';
import type { ChatMessage } from '@/types/assistant';

export const AGENTS_KEY = ['assistant', 'agents'] as const;

export function useAgentsRoster() {
  return useQuery({
    queryKey: AGENTS_KEY,
    queryFn: assistantService.getAgents,
    staleTime: 10_000,
  });
}

export function useAssistantChat() {
  return useMutation({
    mutationFn: (messages: ChatMessage[]) => assistantService.sendChat(messages),
  });
}

/** Confirming changes jobs/applications/agent runs, so the roster is refetched after. */
export function useConfirmAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (token: string) => assistantService.confirmAction(token),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: AGENTS_KEY });
    },
  });
}

export function usePrepareAction() {
  return useMutation({
    mutationFn: (action: string) => assistantService.prepareAction(action),
  });
}
