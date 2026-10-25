/** In-app notification, as returned by GET /api/v1/notifications/. */
export interface AppNotification {
  id: string;
  /** new_jobs | best_match | application_submitted | application_failed | action_required | … */
  kind: string;
  severity: 'info' | 'success' | 'warning' | 'critical' | string;
  title: string;
  body: string | null;
  /** In-app path to open, e.g. "/applications/<id>". */
  link: string | null;
  created_at: string;
  read_at: string | null;
  emailed_at: string | null;
}

export interface NotificationFeed {
  items: AppNotification[];
  unread: number;
}
