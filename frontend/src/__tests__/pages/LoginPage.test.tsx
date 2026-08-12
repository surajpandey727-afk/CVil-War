import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import { server } from '@/__tests__/mocks/server';
import LoginPage from '@/pages/LoginPage';
import { useAuthStore } from '@/store/useAuthStore';

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<div>Dashboard here</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('LoginPage', () => {
  beforeEach(() => useAuthStore.getState().clear());

  it('renders email + password fields and a sign-in button', () => {
    renderLogin();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('signs in with valid credentials and lands on the dashboard', async () => {
    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'a@x.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'password123');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('Dashboard here')).toBeInTheDocument();
  });

  it('shows an error message when login fails', async () => {
    server.use(http.post('/api/v1/auth/login', () => HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })));
    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'a@x.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText(/invalid credentials/i)).toBeInTheDocument();
  });
});
