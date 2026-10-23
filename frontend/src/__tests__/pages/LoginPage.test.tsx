import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import LoginPage from '@/pages/LoginPage';
import { useAuthStore } from '@/store/useAuthStore';

function renderLogin() {
  return render(<MemoryRouter><LoginPage /></MemoryRouter>);
}

async function submit(email = 'me@test.dev', password = 'whatever123') {
  await userEvent.type(screen.getByLabelText(/email/i), email);
  await userEvent.type(screen.getByLabelText(/password/i), password);
  await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
}

describe('LoginPage error handling', () => {
  beforeEach(() => useAuthStore.setState({ token: null, user: null }));

  it('tells the user it is an outage when the server 5xxs, not a credential problem', async () => {
    // A dead database behind the API used to read as "Login failed", making an outage look
    // like a mistyped password. The message must name the outage.
    server.use(http.post('/api/v1/auth/login', () => new HttpResponse(null, { status: 503 })));
    renderLogin();
    await submit();
    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument();
  });

  it('shows a credential message on a 401', async () => {
    server.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({ detail: 'Incorrect email or password' }, { status: 401 })),
    );
    renderLogin();
    await submit();
    expect(await screen.findByText(/incorrect email or password/i)).toBeInTheDocument();
  });

  it('tells the user when the server is unreachable', async () => {
    server.use(http.post('/api/v1/auth/login', () => HttpResponse.error()));
    renderLogin();
    await submit();
    expect(await screen.findByText(/can.t reach the server/i)).toBeInTheDocument();
  });
});
