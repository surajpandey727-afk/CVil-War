import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { AuthShell, AuthField } from '@/components/auth/AuthShell';
import { authService } from '@/services/authService';
import { useAuthStore } from '@/store/useAuthStore';
import type { ApiError } from '@/types/api';

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { access_token } = await authService.login(email, password, rememberMe);
      useAuthStore.setState({ token: access_token });
      const user = await authService.me();
      useAuthStore.getState().setAuth(access_token, user);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      // Distinguish an outage from a bad password. A 5xx (or a dead database behind the API)
      // used to surface as a vague "Login failed", making an infrastructure outage look like
      // the user mistyped their credentials — the exact confusion the audit flagged.
      const status = (err as ApiError).status_code ?? 0;
      if (status === 0) {
        setError('Can’t reach the server. Check your connection and try again.');
      } else if (status >= 500) {
        setError('The service is temporarily unavailable — the server or database may be down. Please try again shortly.');
      } else {
        setError((err as ApiError).detail || 'Incorrect email or password.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to your job-search copilot."
      error={error}
      onSubmit={handleSubmit}
      submitting={submitting}
      submitLabel={submitting ? 'Signing in…' : 'Sign in'}
      footer={<>No account? <Link to="/register" style={{ color: 'var(--accent)', fontWeight: 700, textDecoration: 'none' }}>Create one</Link></>}
    >
      <AuthField id="email" label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
      <AuthField id="password" label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '-4px 0 10px' }}>
        <label htmlFor="remember-me" style={{ display: 'flex', alignItems: 'center', gap: 7, font: '500 12px/1 var(--font)', color: 'var(--text-3)', cursor: 'pointer' }}>
          <input
            id="remember-me"
            type="checkbox"
            checked={rememberMe}
            onChange={(e) => setRememberMe(e.target.checked)}
            style={{ margin: 0, cursor: 'pointer' }}
          />
          Stay signed in
        </label>
        <Link to="/forgot-password" style={{ font: '600 12px/1 var(--font)', color: 'var(--accent)', textDecoration: 'none' }}>Forgot password?</Link>
      </div>
    </AuthShell>
  );
}
