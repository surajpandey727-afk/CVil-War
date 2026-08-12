import { create } from 'zustand';
import type { User } from '@/types/auth';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

/**
 * A non-sensitive marker in localStorage recording that a session was once established. The
 * refresh token itself is an httpOnly cookie JS cannot read, so this hint is the only way the
 * boot code can tell a returning user (worth a silent-refresh probe) from a first-time / logged-out
 * visitor (for whom the probe just 401s and logs console noise — BUG-005). It gates the probe only;
 * it is never trusted as proof of auth.
 */
export const SESSION_HINT_KEY = 'aa_session_hint';

function writeSessionHint(present: boolean): void {
  try {
    if (present) localStorage.setItem(SESSION_HINT_KEY, '1');
    else localStorage.removeItem(SESSION_HINT_KEY);
  } catch {
    /* storage unavailable (private mode / disabled) — degrade to always-probe */
  }
}

/** Whether a session was previously established on this device (gates the boot refresh probe). */
export function hasSessionHint(): boolean {
  try {
    return localStorage.getItem(SESSION_HINT_KEY) === '1';
  } catch {
    return true; // can't read storage → don't suppress the probe
  }
}

interface AuthStoreState {
  /** In-memory access token (never persisted; restored via silent refresh in Phase 1). */
  token: string | null;
  user: User | null;
  status: AuthStatus;

  setAuth: (token: string, user: User) => void;
  setStatus: (status: AuthStatus) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthStoreState>((set) => ({
  token: null,
  user: null,
  status: 'loading',

  setAuth: (token, user) => {
    writeSessionHint(true);
    set({ token, user, status: 'authenticated' });
  },
  setStatus: (status) => set({ status }),
  clear: () => {
    writeSessionHint(false);
    set({ token: null, user: null, status: 'unauthenticated' });
  },
}));
