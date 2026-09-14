import { create } from 'zustand';

interface Notification {
  id: string;
  message: string;
  severity: 'success' | 'error' | 'warning' | 'info';
}

/** A human-in-the-loop challenge the agent hit (CAPTCHA/2FA), awaiting the user's response. */
export interface PendingIntervention {
  application_id: string;
  kind: string;
  prompt: string;
  /** The exact page the browser stopped on (set for kind="captcha" — a CAPTCHA cannot be
   *  cleared by typing a code into this dashboard the way a 2FA prompt can). */
  url?: string;
  /** The filled-in form, as a screenshot (set for kind="submit_confirmation" — this is what
   *  the operator is actually approving, since a headless run has no window of its own for
   *  them to go look at the way a headed CAPTCHA pause does). Base64 PNG, no data: prefix. */
  screenshot_b64?: string;
}

/** One live step of an in-progress browser-automation run, as published by
 *  ``core.automation.runtime.observe.make_step_observer`` — e.g. "step 4: click_submit_button". */
export interface FillStep {
  detail: string;
  at: string;
}

//: Steps kept per application — a rolling window, not a full history (this mirrors the live
//: WS feed, not the persisted trajectory the Evidence panel reads after the run finishes).
const MAX_STEPS_PER_APP = 50;

interface AppStoreState {
  /** Active notification for the global toaster. */
  notification: Notification | null;
  /** Whether the backend WebSocket is connected. */
  wsConnected: boolean;
  /** A pending CAPTCHA/2FA intervention the user must resolve, or null. */
  pendingIntervention: PendingIntervention | null;
  /** Live step-by-step fill activity, keyed by application id, most recent last. */
  fillActivity: Record<string, FillStep[]>;

  showNotification: (message: string, severity?: Notification['severity']) => void;
  clearNotification: () => void;
  setWsConnected: (connected: boolean) => void;
  setIntervention: (iv: PendingIntervention) => void;
  clearIntervention: () => void;
  appendFillStep: (applicationId: string, detail: string) => void;
  clearFillActivity: (applicationId: string) => void;
}

export const useAppStore = create<AppStoreState>((set) => ({
  notification: null,
  wsConnected: false,
  pendingIntervention: null,
  fillActivity: {},

  showNotification: (message, severity = 'info') =>
    set({
      notification: {
        id: crypto.randomUUID(),
        message,
        severity,
      },
    }),

  clearNotification: () => set({ notification: null }),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setIntervention: (iv) => set({ pendingIntervention: iv }),
  clearIntervention: () => set({ pendingIntervention: null }),

  appendFillStep: (applicationId, detail) =>
    set((state) => {
      const existing = state.fillActivity[applicationId] ?? [];
      const next = [...existing, { detail, at: new Date().toISOString() }].slice(-MAX_STEPS_PER_APP);
      return { fillActivity: { ...state.fillActivity, [applicationId]: next } };
    }),

  clearFillActivity: (applicationId) =>
    set((state) => {
      const { [applicationId]: _drop, ...rest } = state.fillActivity;
      return { fillActivity: rest };
    }),
}));
