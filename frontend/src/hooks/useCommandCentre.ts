import { useQuery } from '@tanstack/react-query';

import { commandCentreService } from '@/services/commandCentreService';

/**
 * Deadlines move on their own, so these are refetched on an interval rather than only on
 * mutation: an assessment becomes urgent and a session goes stale with no user action to
 * hang an invalidation off. 60s is frequent enough that an hours-away deadline is never
 * badly wrong, without polling hard.
 */
const LIVE_REFRESH_MS = 60_000;

export function useCommandCentreSummary() {
  return useQuery({
    queryKey: ['command-centre', 'summary'],
    queryFn: () => commandCentreService.summary(),
    refetchInterval: LIVE_REFRESH_MS,
    refetchOnWindowFocus: true,
  });
}

export function useActionQueue() {
  return useQuery({
    queryKey: ['command-centre', 'queue'],
    queryFn: () => commandCentreService.queue(),
    refetchInterval: LIVE_REFRESH_MS,
    refetchOnWindowFocus: true,
  });
}

export function useApplicationTimeline(applicationId: string | null) {
  return useQuery({
    queryKey: ['command-centre', 'timeline', applicationId],
    queryFn: () => commandCentreService.timeline(applicationId!),
    enabled: Boolean(applicationId),
  });
}
