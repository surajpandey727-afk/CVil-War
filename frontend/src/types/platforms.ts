/**
 * Platform management. Mirrors the backend `PlatformsResponse`.
 *
 * Assembled server-side from the source registry joined to this user's sessions, so Sources
 * and Settings cannot disagree about what the product supports or what is connected — the
 * defect this replaced had Settings hard-coding four platforms against a registry of 55.
 *
 * `actions` carries availability and a reason, because whether a source needs a login is a
 * property of its adapter, not something the browser can work out.
 */

export interface PlatformAction {
  key: 'toggle' | 'connect' | 'disconnect' | 'test' | string;
  label: string;
  available: boolean;
  /** Why it is unavailable. Empty when it is available. */
  reason: string;
}

export interface PlatformStatus {
  key: string;
  label: string;
  tier: string;
  health: string;
  implemented: boolean;
  needs_credential: boolean;
  capabilities: string[];
  enabled: boolean;
  connected: boolean;
  connection_state: string;
  /** Masked, e.g. `sur***@example.com`. Never a credential. */
  account: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  detail: string | null;
  last_error: string | null;
  actions: PlatformAction[];
}

export interface PlatformsResponse {
  platforms: PlatformStatus[];
  total: number;
  /** Sources with a working adapter — the number that matters for discovery. */
  usable: number;
  connected: number;
}
