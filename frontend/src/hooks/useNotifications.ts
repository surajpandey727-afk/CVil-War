import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as notificationService from '@/services/notificationService';

export const NOTIFICATIONS_KEY = ['notifications'] as const;

/**
 * The bell's feed. Polled once a minute: notifications come from the API (searches, approvals)
 * and from the worker on another machine, so there is no single client event to invalidate on.
 * Polling pauses while the tab is hidden (React Query's default for refetchInterval).
 */
export function useNotifications() {
  return useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: () => notificationService.getNotifications(),
    refetchInterval: 60_000,
    staleTime: 15_000,
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: notificationService.markNotificationRead,
    onSettled: () => qc.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
  });
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: notificationService.markAllNotificationsRead,
    onSettled: () => qc.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
  });
}
