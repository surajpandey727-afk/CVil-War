import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import ForgotPasswordPage from '@/pages/ForgotPasswordPage';

const renderPage = () =>
  render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>,
  );

describe('ForgotPasswordPage', () => {
  it('submits the email and shows a uniform confirmation', async () => {
    let body: { email?: string } | null = null;
    server.use(
      http.post('/api/v1/auth/forgot-password', async ({ request }) => {
        body = (await request.json()) as { email: string };
        return HttpResponse.json({
          message: 'If that email is registered, a password-reset link is on its way.',
        });
      }),
    );
    renderPage();
    await userEvent.type(screen.getByLabelText(/email/i), 'someone@x.com');
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }));
    expect(await screen.findByText(/check your email/i)).toBeInTheDocument();
    expect(body!.email).toBe('someone@x.com');
  });

  it('links back to sign in', () => {
    renderPage();
    expect(screen.getByRole('link', { name: /back to sign in/i })).toHaveAttribute('href', '/login');
  });
});
