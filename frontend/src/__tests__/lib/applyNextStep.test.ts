/**
 * What each application row says it is waiting for. Every state must name its blocker and a
 * way forward; the bug these pin is a row that said nothing useful ("Approved") or the wrong
 * thing ("no job board is connected" beside "65 sources enabled").
 */
import { describe, it, expect } from 'vitest';

import { HOST_COMMAND, needsSignIn, nextStep } from '@/lib/applyNextStep';
import type { Application } from '@/types/application';
import type { PlatformStatus } from '@/types/platforms';

const base = {
  id: 'a', job_id: 'j', job_title: 'PM', company: 'Acme', resume_id: 'r', resume_name: 'cv',
  resume_type: 'base', resume_ats_score: null, resume_archived: false, has_cover_letter: false,
  resume_version_id: null, status: 'pending_review', apply_mode: 'review',
  submission_method: 'none', confirmation_state: 'pending', confirmation_detail: null,
  ats_score: null, cover_letter_path: null, applied_at: null, response_date: null, notes: null,
  created_at: '2026-10-25T00:00:00Z', updated_at: '2026-10-25T00:00:00Z',
} as Application;

const linkedin = {
  key: 'linkedin', label: 'LinkedIn', connected: false,
  actions: [{ key: 'connect', label: 'Connect', available: true, reason: '' }],
} as PlatformStatus;

describe('nextStep', () => {
  it('a careers-page application needs no sign-in', () => {
    expect(needsSignIn('careers:monzo', [linkedin])).toBeNull();
    expect(nextStep({ ...base, portal: 'careers:monzo' }, [linkedin]).headline).toBe('Waiting for your approval');
  });

  it('a career page whose connect action is unavailable needs no sign-in', () => {
    // Seen live: Monzo and Wise rows said "needs your Monzo sign-in". Their connect action
    // exists but is unavailable ("This source is a public API and needs no login").
    const monzo = {
      key: 'careers:monzo', label: 'Monzo', connected: false,
      actions: [{ key: 'connect', label: 'Connect', available: false, reason: 'needs no login' }],
    } as PlatformStatus;
    expect(needsSignIn('careers:monzo', [monzo])).toBeNull();
    expect(nextStep({ ...base, status: 'approved', portal: 'careers:monzo' }, [monzo]).kind).toBe('host');
  });

  it('a LinkedIn application says it will also need the LinkedIn sign-in', () => {
    const step = nextStep({ ...base, portal: 'linkedin' }, [linkedin]);
    expect(step.kind).toBe('approve');
    expect(step.headline).toMatch(/then your LinkedIn sign-in/);
  });

  it('approved with nothing missing is waiting for the automation host, with the command', () => {
    const step = nextStep({ ...base, status: 'approved', approved: true, portal: 'careers:monzo' }, [linkedin]);
    expect(step.kind).toBe('host');
    expect(step.detail).toContain(HOST_COMMAND);
  });

  it('approved through LinkedIn without a session asks for the sign-in', () => {
    const step = nextStep({ ...base, status: 'approved', approved: true, portal: 'linkedin' }, [linkedin]);
    expect(step.kind).toBe('sign_in');
    expect(step.platform?.label).toBe('LinkedIn');
  });

  it('a connected platform is not a blocker', () => {
    const connected = { ...linkedin, connected: true };
    expect(nextStep({ ...base, status: 'approved', portal: 'linkedin' }, [connected]).kind).toBe('host');
  });

  it('a run paused at a CAPTCHA offers to resume in a visible window, not to approve', () => {
    const step = nextStep({ ...base, blocked_reason: 'captcha', portal: 'reed' }, []);
    expect(step.kind).toBe('verify');
    expect(step.detail).toMatch(/never solves CAPTCHAs/);
  });

  it('a hold says why, from the policy note', () => {
    const step = nextStep({ ...base, status: 'queued', approved: true, notes: 'Outside your run window.' }, []);
    expect(step.kind).toBe('hold');
    expect(step.detail).toBe('Outside your run window.');
  });

  it('a settled application has no next step', () => {
    expect(nextStep({ ...base, status: 'applied' }, []).kind).toBe('none');
  });
});
