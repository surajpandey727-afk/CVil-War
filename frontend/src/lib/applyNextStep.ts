/**
 * What one application is waiting for, in plain words, and the one thing that moves it.
 *
 * The Applications screen used to show a single banner — "no job board is connected" — over
 * every row, beside a Sources page saying "65 enabled". Those are different things and the
 * screen never said so: *sources* find jobs (read-only searches, no account needed);
 * *submitting* fills in a form in a real browser, which runs on the owner's PC, and for
 * LinkedIn / Indeed / Reed it needs the owner's own signed-in session for that site. A row now
 * says which of those it is actually blocked on.
 */
import type { Application } from '@/types/application';
import type { PlatformStatus } from '@/types/platforms';

export type NextStepKind =
  | 'approve' // waiting for the owner to approve
  | 'verify' // a run stopped at a CAPTCHA/identity check; resume opens a visible window
  | 'sign_in' // approved (or approvable) but this board needs the owner's session
  | 'host' // approved, nothing missing — waiting for the automation host on the PC
  | 'hold' // a pacing rule (run window, daily cap) is holding it
  | 'running' // being submitted right now
  | 'none';

export interface NextStep {
  kind: NextStepKind;
  headline: string;
  detail?: string;
  /** The board to sign in to, when `kind` is `sign_in`. */
  platform?: { key: string; label: string };
}

/** The PowerShell command that starts the automation host (see docs/LOCAL_SETUP.md). */
export const HOST_COMMAND = '.\\scripts\\db-worker.ps1 -Start';

/** True when applying through this board needs the owner's signed-in session and none is saved. */
export function needsSignIn(portal: string | null | undefined, platforms: PlatformStatus[] | undefined): PlatformStatus | null {
  if (!portal || !platforms) return null;
  const p = platforms.find((x) => x.key === portal);
  if (!p || p.connected) return null;
  // Every source lists a "connect" action; on keyless boards and career pages it is
  // unavailable ("needs no login"). Only an available one means a sign-in is required.
  return p.actions.some((a) => a.key === 'connect' && a.available) ? p : null;
}

export function nextStep(app: Application, platforms: PlatformStatus[] | undefined): NextStep {
  const signIn = needsSignIn(app.portal, platforms);
  const signInStep = (lead: string): NextStep => ({
    kind: 'sign_in',
    headline: `${lead} needs your ${signIn!.label} sign-in to be sent`,
    detail: `Sign in to ${signIn!.label} once in the window CVil-War opens on your PC; only the session is kept, never your password. Or apply yourself and mark it applied.`,
    platform: { key: signIn!.key, label: signIn!.label },
  });
  const notes = (app.notes ?? '').trim();

  if (app.status === 'pending_review' && app.blocked_reason) {
    return {
      kind: 'verify',
      headline: `Paused: ${app.portal ?? 'the site'} asked for a human check`,
      detail: 'Resume retries in a visible browser window on your PC so you can complete the check yourself. CVil-War never solves CAPTCHAs.',
    };
  }
  switch (app.status) {
    case 'pending_review':
      return {
        kind: 'approve',
        headline: signIn
          ? `Waiting for your approval — then your ${signIn.label} sign-in`
          : 'Waiting for your approval',
        detail: notes || undefined,
      };
    case 'approved':
      if (signIn) return signInStep('Approved —');
      if (notes.startsWith('Waiting for setup')) {
        return { kind: 'sign_in', headline: 'Approved — needs setup before it can be sent', detail: notes };
      }
      return {
        kind: 'host',
        headline: 'Approved — waiting for the automation host on your PC',
        detail: `Submissions run in a real browser on your machine, not on the website. If this has sat here for more than a few minutes the host isn't running: start it with ${HOST_COMMAND}.`,
      };
    case 'queued':
      if (app.approved && signIn) return signInStep('Approved —');
      return {
        kind: 'hold',
        headline: app.approved ? 'Approved — on hold until a rule clears' : 'Queued',
        detail: notes || `Waiting for the automation host on your PC (${HOST_COMMAND}).`,
      };
    case 'applying':
      return { kind: 'running', headline: 'Being submitted now' };
    default:
      return { kind: 'none', headline: '' };
  }
}
