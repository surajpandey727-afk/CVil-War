import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { AGENT_RUNS_KEY } from '@/hooks/useAgentRuns';
import type { WSMessage } from '@/hooks/useWebSocket';
import { useAppStore, type PendingIntervention } from '@/store/useAppStore';

/** Ask for desktop-notification permission once a blocker actually needs showing — asking
 *  cold on page load gets ignored/denied far more often than asking at the moment of need. */
function notifyDesktop(title: string, body: string): void {
  if (typeof window === 'undefined' || !('Notification' in window)) return;
  if (Notification.permission === 'granted') {
    new Notification(title, { body });
  } else if (Notification.permission !== 'denied') {
    void Notification.requestPermission().then((permission) => {
      if (permission === 'granted') new Notification(title, { body });
    });
  }
}

/**
 * Reacts to real-time WebSocket events: `application_progress` invalidates the cached
 * application queries (live status), `agent_state_changed` invalidates the Agent Ops graph,
 * and `intervention_required` raises a notification prompting the user to resolve a
 * CAPTCHA/2FA challenge — including a desktop notification, since a blocker sitting unnoticed
 * in a background tab defeats the point of surfacing it live.
 */
export function useApplicationEvents(lastMessage: WSMessage | null): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type === 'application_progress') {
      void queryClient.invalidateQueries({ queryKey: ['applications'] });
      const payload = lastMessage.payload as { application_id?: string; detail?: string } | undefined;
      if (payload?.application_id && payload.detail) {
        useAppStore.getState().appendFillStep(payload.application_id, payload.detail);
      }
    } else if (lastMessage.type === 'agent_state_changed') {
      // An agent just started, finished, or errored — refresh the Agent Ops graph/log
      // immediately rather than waiting on its own poll, so "live" actually means live.
      void queryClient.invalidateQueries({ queryKey: AGENT_RUNS_KEY });
    } else if (lastMessage.type === 'intervention_required') {
      const iv = lastMessage.payload as unknown as PendingIntervention;
      useAppStore.getState().setIntervention(iv);
      const isCaptcha = iv.kind === 'captcha';
      useAppStore
        .getState()
        .showNotification('A job application needs your input (CAPTCHA/2FA).', 'warning');
      notifyDesktop(
        isCaptcha ? 'Verification needed to continue applying' : 'Application needs your input',
        iv.prompt || 'Open the dashboard to resolve it.',
      );
    }
  }, [lastMessage, queryClient]);
}
