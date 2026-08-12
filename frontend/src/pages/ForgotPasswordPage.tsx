import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { AuthShell, AuthField } from '@/components/auth/AuthShell';
import { AuthNotice } from '@/components/auth/AuthNotice';
import { authService } from '@/services/authService';
import type { ApiError } from '@/types/api';

const backToSignIn = (
  <>
    Remembered it?{' '}
    <Link to="/login" style={{ color: 'var(--accent)', fontWeight: 700, textDecoration: 'none' }}>
      Back to sign in
    </Link>
  </>
);

/**
 * Password-reset request screen. Submits the email to `/auth/forgot-password` and then always
 * shows the same confirmation regardless of whether the account exists (no enumeration).
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await authService.forgotPassword(email);
      setSent(true);
    } catch (err) {
      setError((err as ApiError).detail ?? 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (sent) {
    return (
      <AuthNotice
        icon="mail"
        title="Check your email"
        body={`If an account exists for ${email}, we've sent a password-reset link. It expires shortly.`}
        footer={backToSignIn}
      />
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="Enter your email and we'll send you a reset link."
      error={error}
      onSubmit={onSubmit}
      submitting={submitting}
      submitLabel={submitting ? 'Sending…' : 'Send reset link'}
      footer={backToSignIn}
    >
      <AuthField
        id="reset-email"
        label="Email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        autoComplete="email"
        required
      />
    </AuthShell>
  );
}
