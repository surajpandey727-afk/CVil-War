import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import SystemStatePage from '@/pages/SystemStatePage';

const renderState = (code: '404' | '403' | '500') =>
  render(
    <MemoryRouter>
      <SystemStatePage code={code} />
    </MemoryRouter>,
  );

describe('SystemStatePage', () => {
  it('renders the 404 state with a back-to-dashboard link', () => {
    renderState('404');
    expect(screen.getByText('404')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /page not found/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /back to dashboard/i })).toHaveAttribute('href', '/dashboard');
  });

  it('renders the 403 access-denied state', () => {
    renderState('403');
    expect(screen.getByText('403')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /access denied/i })).toBeInTheDocument();
  });

  it('renders the 500 error state', () => {
    renderState('500');
    expect(screen.getByText('500')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /something went wrong/i })).toBeInTheDocument();
  });
});
