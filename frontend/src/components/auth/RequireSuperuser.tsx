import { type ReactNode } from 'react';

import { useAuthStore } from '@/store/useAuthStore';
import SystemStatePage from '@/pages/SystemStatePage';

/** Gate for superuser-only routes (e.g. System Health). Non-superusers get the 403 state. */
export function RequireSuperuser({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!user?.is_superuser) {
    return <SystemStatePage code="403" />;
  }
  return <>{children}</>;
}
