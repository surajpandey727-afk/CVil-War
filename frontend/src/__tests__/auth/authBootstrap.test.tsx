import { describe, it, expect, beforeEach } from 'vitest';
import { StrictMode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { AuthProvider } from '@/context/AuthProvider';
import { server } from '@/__tests__/mocks/server';
import { useAuthStore, SESSION_HINT_KEY } from '@/store/useAuthStore';

describe('AuthProvider boot refresh', () => {
  beforeEach(() => {
    useAuthStore.getState().clear(); // also clears the session hint
  });

  it('issues only one /auth/refresh even when the effect double-invokes (StrictMode)', async () => {
    // A rotating-refresh backend revokes the whole token family if the *same* refresh
    // cookie is presented twice. React StrictMode double-invokes mount effects in dev,
    // and multiple tabs do the same in prod — so the boot refresh must be single-flighted.
    //
    // The probe only runs for a device that previously held a session (BUG-005), so the
    // hint has to be present or AuthProvider short-circuits and this asserts nothing.
    localStorage.setItem(SESSION_HINT_KEY, '1');

    let refreshCalls = 0;
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshCalls += 1;
        return HttpResponse.json({ access_token: 'boot-token', token_type: 'bearer' });
      }),
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({ id: 'u1', email: 'boot@x.com', full_name: null, is_active: true }),
      ),
    );

    render(
      <StrictMode>
        <AuthProvider>
          <div>ready</div>
        </AuthProvider>
      </StrictMode>,
    );

    await waitFor(() => expect(useAuthStore.getState().status).toBe('authenticated'));
    expect(screen.getByText('ready')).toBeInTheDocument();
    expect(refreshCalls).toBe(1);
  });

  it('skips the probe entirely when there is no session hint', async () => {
    // A first-time / logged-out visitor has no refresh cookie, so probing guarantees a 401
    // the browser logs as a console error (BUG-005). Boot must resolve straight to
    // "unauthenticated" without touching the network.
    let refreshCalls = 0;
    server.use(
      http.post('/api/v1/auth/refresh', () => {
        refreshCalls += 1;
        return HttpResponse.json({ access_token: 'nope', token_type: 'bearer' });
      }),
    );

    render(
      <AuthProvider>
        <div>ready</div>
      </AuthProvider>,
    );

    await waitFor(() => expect(useAuthStore.getState().status).toBe('unauthenticated'));
    expect(screen.getByText('ready')).toBeInTheDocument();
    expect(refreshCalls).toBe(0);
  });
});
