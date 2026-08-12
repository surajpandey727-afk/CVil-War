import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import OnboardingPage from '@/pages/OnboardingPage';

function renderOnboarding() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route path="/dashboard" element={<div>Dashboard here</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('OnboardingPage', () => {
  it('starts on the welcome step', () => {
    renderOnboarding();
    expect(screen.getByText(/welcome to autoapply/i)).toBeInTheDocument();
  });

  it('advances to the résumé step on continue', async () => {
    renderOnboarding();
    await userEvent.click(screen.getByRole('button', { name: /continue|get started/i }));
    expect(screen.getByLabelText(/upload résumé/i)).toBeInTheDocument();
  });

  it('finishes onboarding by landing on the dashboard', async () => {
    renderOnboarding();
    for (let i = 0; i < 3; i++) {
      await userEvent.click(screen.getByRole('button', { name: /continue|get started|go to dashboard/i }));
    }
    expect(screen.getByText('Dashboard here')).toBeInTheDocument();
  });
});
