import api from '@/services/api';
import type { RegisterRequest, TokenResponse, User } from '@/types/auth';

/** Authentication API calls. */
export const authService = {
  async register(data: RegisterRequest): Promise<User> {
    const res = await api.post<User>('/auth/register', data);
    return res.data;
  },

  /** Log in via the OAuth2 password flow (form-encoded username/password).
   *
   *  `rememberMe` (default true) only changes whether the refresh cookie survives a browser
   *  restart — see the backend's `_set_refresh_cookie`. Off signs the operator out the moment
   *  they close the browser, on a shared or borrowed machine they'd rather not stay signed
   *  into indefinitely. */
  async login(email: string, password: string, rememberMe = true): Promise<TokenResponse> {
    const form = new URLSearchParams();
    form.append('username', email);
    form.append('password', password);
    form.append('remember_me', String(rememberMe));
    const res = await api.post<TokenResponse>('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return res.data;
  },

  async me(): Promise<User> {
    const res = await api.get<User>('/auth/me');
    return res.data;
  },

  /** Request a password-reset link. Always resolves the same way (no account enumeration). */
  async forgotPassword(email: string): Promise<void> {
    await api.post('/auth/forgot-password', { email });
  },

  /** Redeem a reset token and set a new password. Rejects on an invalid/expired token. */
  async resetPassword(token: string, password: string): Promise<void> {
    await api.post('/auth/reset-password', { token, password });
  },

  /** Silent refresh via the httpOnly refresh cookie. Endpoint lands in Phase 1. */
  async refresh(): Promise<TokenResponse> {
    const res = await api.post<TokenResponse>('/auth/refresh');
    return res.data;
  },

  /** Short-lived ticket for authenticating the WebSocket handshake. */
  async getWsTicket(): Promise<string> {
    const res = await api.get<{ ticket: string }>('/auth/ws-ticket');
    return res.data.ticket;
  },
};
