import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { AuthShell, AuthField } from '@/components/auth/AuthShell';
import { AuthNotice } from '@/components/auth/AuthNotice';
import { authService } from '@/services/authService';
import type { ApiError } from '@/types/api';

const signInLink = (
  <>
    <Link to="/login" style={{ color: 'var(--accent)', fontWeight: 700, textDecoration: 'none' }}>
      Sign in
    </Link>{' '}
    with your new password.
  </>
);

/**
 * Set a new password using the token from the emailed reset link (`/reset-password?token=…`).
 * On success it shows a confirmation linking back to sign-in; all sessions were revoked server-side.
 */
export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get('token');

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  if (!token) {
    return (
      <AuthNotice
        icon="alert"
        title="Invalid reset link"
        body="This password-reset link is invalid or missing its token. Request a new one to continue."
        footer={
          <Link to="/forgot-password" style={{ color: 'var(--accent)', fontWeight: 700, textDecoration: 'none' }}>
            Request a new link
          </Link>
        }
      />
    );
  }

  if (done) {
    return (
      <AuthNotice
        icon="shield"
        title="Password reset"
        body="Your password has been updated and all existing sessions were signed out."
        footer={signInLink}
      />
    );
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      await authService.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError((err as ApiError).detail ?? 'Could not reset your password. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      title="Choose a new password"
      subtitle="Enter a new password for your account."
      error={error}
      onSubmit={onSubmit}
      submitting={submitting}
      submitLabel={submitting ? 'Resetting…' : 'Reset password'}
      footer={
        <>
          Changed your mind?{' '}
          <Link to="/login" style={{ color: 'var(--accent)', fontWeight: 700, textDecoration: 'none' }}>
            Back to sign in
          </Link>
        </>
      }
    >
      <AuthField
        id="new-password"
        label="New password"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoComplete="new-password"
        required
      />
      <AuthField
        id="confirm-password"
        label="Confirm password"
        type="password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        autoComplete="new-password"
        required
      />
    </AuthShell>
  );
}
