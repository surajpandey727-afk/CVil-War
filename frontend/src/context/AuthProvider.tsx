import { useEffect, type ReactNode } from 'react';

import { authService } from '@/services/authService';
import { refreshAccessToken } from '@/services/api';
import { useAuthStore, hasSessionHint } from '@/store/useAuthStore';

/**
 * Initializes auth state on boot via a silent refresh (httpOnly cookie). In Phase 0
 * the `/auth/refresh` endpoint does not exist yet, so boot resolves to
 * "unauthenticated" and the user logs in explicitly; Phase 1 enables persistence.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const status = useAuthStore((s) => s.status);

  useEffect(() => {
    let active = true;
    // A fresh / logged-out visitor has no session hint. Skip the refresh probe entirely so it
    // doesn't fire a guaranteed 401 (which the browser logs as a console error — BUG-005). Only
    // a device that previously held a session is worth probing.
    if (!hasSessionHint()) {
      useAuthStore.getState().clear();
      return () => {
        active = false;
      };
    }
    (async () => {
      try {
        // Go through the shared single-flight refresh so StrictMode's dev double-invoke
        // (and multi-tab boots) collapse to ONE /auth/refresh — presenting the rotating
        // cookie twice would trip reuse-detection and revoke the session. It also sets
        // the token in the store so the me() call below is authenticated.
        const access_token = await refreshAccessToken();
        const user = await authService.me();
        if (active) {
          useAuthStore.getState().setAuth(access_token, user);
        }
      } catch {
        if (active) {
          useAuthStore.getState().clear();
        }
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (status === 'loading') {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg)' }}>
        <div
          aria-label="Loading"
          style={{ width: 32, height: 32, borderRadius: '50%', border: '3px solid var(--surface-2)', borderTopColor: 'var(--accent)', animation: 'aaSpin .8s linear infinite' }}
        />
      </div>
    );
  }

  return <>{children}</>;
}
