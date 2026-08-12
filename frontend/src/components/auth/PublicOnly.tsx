import { type ReactNode } from 'react';
import { Navigate } from 'react-router-dom';

import { useAuthStore } from '@/store/useAuthStore';

interface PublicOnlyProps {
  children: ReactNode;
  /**
   * Where to send an authenticated user. Defaults to /dashboard.
   *
   * `/register` passes `/onboarding`: registering flips auth to `authenticated` while the
   * user is still on the register route, so a hard-coded /dashboard redirect would race
   * RegisterPage's own `navigate('/onboarding')` and skip onboarding entirely (BUG-002).
   */
  redirectTo?: string;
}

/**
 * Gate for logged-out-only routes (landing, login, register, forgot-password): sends an
 * already-authenticated user to `redirectTo` instead of showing them the public page.
 *
 * The `loading` status is not handled here — `AuthProvider` renders a spinner instead of the
 * router until auth resolves, so a route guard only ever sees a settled status.
 */
export function PublicOnly({ children, redirectTo = '/dashboard' }: PublicOnlyProps) {
  const status = useAuthStore((s) => s.status);

  if (status === 'authenticated') {
    return <Navigate to={redirectTo} replace />;
  }
  return <>{children}</>;
}
