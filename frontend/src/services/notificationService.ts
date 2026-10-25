import api from './api';
import type { NotificationFeed } from '@/types/notifications';

/** Newest notifications plus the unread count, in one request. */
export async function getNotifications(limit = 30): Promise<NotificationFeed> {
  const { data } = await api.get<NotificationFeed>('/notifications/', { params: { limit } });
  return data;
}

export async function markNotificationRead(id: string): Promise<void> {
  await api.post(`/notifications/${encodeURIComponent(id)}/read`);
}

export async function markAllNotificationsRead(): Promise<void> {
  await api.post('/notifications/read-all');
}
