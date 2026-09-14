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
    expect(screen.getByText(/welcome to cvil-war/i)).toBeInTheDocument();
  });

  it('advances to the role-targets step on continue', async () => {
    renderOnboarding();
    await userEvent.click(screen.getByRole('button', { name: /continue|get started/i }));
    expect(screen.getByText(/what roles are you targeting/i)).toBeInTheDocument();
  });

  it('advances to the résumé step after adding a role target', async () => {
    renderOnboarding();
    await userEvent.click(screen.getByRole('button', { name: /continue|get started/i }));
    await userEvent.click(screen.getByRole('button', { name: 'Data Analyst' }));
    expect(screen.getByText('Data Analyst')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /continue/i }));
    expect(screen.getByLabelText(/upload résumé/i)).toBeInTheDocument();
  });

  it('lets the operator type a custom role title and remove it', async () => {
    renderOnboarding();
    await userEvent.click(screen.getByRole('button', { name: /continue|get started/i }));
    await userEvent.type(screen.getByLabelText(/job title/i), 'AI Product Manager{enter}');
    expect(screen.getByText('AI Product Manager')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /remove ai product manager/i }));
    expect(screen.queryByText('AI Product Manager')).not.toBeInTheDocument();
  });

  it('finishes onboarding by landing on the dashboard', async () => {
    renderOnboarding();
    for (let i = 0; i < 4; i++) {
      await userEvent.click(screen.getByRole('button', { name: /continue|get started|go to dashboard/i }));
    }
    expect(screen.getByText('Dashboard here')).toBeInTheDocument();
  });
});
