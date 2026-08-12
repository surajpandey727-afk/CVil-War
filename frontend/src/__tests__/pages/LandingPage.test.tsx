import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import LandingPage from '@/pages/LandingPage';

function renderLanding() {
  return render(<MemoryRouter><LandingPage /></MemoryRouter>);
}

describe('LandingPage', () => {
  it('shows a hero headline', () => {
    renderLanding();
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
  });

  it('has a get-started CTA linking to register', () => {
    renderLanding();
    const ctas = screen.getAllByRole('link', { name: /get started|create.*account|start free/i });
    expect(ctas.some((a) => a.getAttribute('href') === '/register')).toBe(true);
  });

  it('has a sign-in link', () => {
    renderLanding();
    const links = screen.getAllByRole('link', { name: /sign in|log ?in/i });
    expect(links.some((a) => a.getAttribute('href') === '/login')).toBe(true);
  });
});
