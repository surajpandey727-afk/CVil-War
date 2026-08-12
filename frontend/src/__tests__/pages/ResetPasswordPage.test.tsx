import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import ResetPasswordPage from '@/pages/ResetPasswordPage';

const renderAt = (entry: string) =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <ResetPasswordPage />
    </MemoryRouter>,
  );

describe('ResetPasswordPage', () => {
  it('submits the token + new password and shows success', async () => {
    let body: { token?: string; password?: string } | null = null;
    server.use(
      http.post('/api/v1/auth/reset-password', async ({ request }) => {
        body = (await request.json()) as { token: string; password: string };
        return HttpResponse.json({ message: 'Your password has been reset. Please sign in.' });
      }),
    );
    renderAt('/reset-password?token=tok-123');
    await userEvent.type(screen.getByLabelText(/^new password/i), 'newpassword456');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'newpassword456');
    await userEvent.click(screen.getByRole('button', { name: /reset password/i }));
    expect(await screen.findByRole('link', { name: /sign in/i })).toBeInTheDocument();
    expect(body).toEqual({ token: 'tok-123', password: 'newpassword456' });
  });

  it('rejects mismatched passwords client-side (sends no request)', async () => {
    let called = false;
    server.use(
      http.post('/api/v1/auth/reset-password', () => {
        called = true;
        return HttpResponse.json({ message: 'ok' });
      }),
    );
    renderAt('/reset-password?token=tok-123');
    await userEvent.type(screen.getByLabelText(/^new password/i), 'newpassword456');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'different789');
    await userEvent.click(screen.getByRole('button', { name: /reset password/i }));
    expect(await screen.findByText(/don.t match|do not match/i)).toBeInTheDocument();
    expect(called).toBe(false);
  });

  it('shows an error for an invalid or expired token', async () => {
    server.use(
      http.post('/api/v1/auth/reset-password', () =>
        HttpResponse.json({ detail: 'Invalid or expired reset token' }, { status: 401 }),
      ),
    );
    renderAt('/reset-password?token=bad');
    await userEvent.type(screen.getByLabelText(/^new password/i), 'newpassword456');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'newpassword456');
    await userEvent.click(screen.getByRole('button', { name: /reset password/i }));
    expect(await screen.findByText(/invalid or expired/i)).toBeInTheDocument();
  });

  it('shows an invalid-link message when the token is missing', () => {
    renderAt('/reset-password');
    expect(screen.getByText(/invalid or missing/i)).toBeInTheDocument();
  });
});
