import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ErrorBoundary from '@/components/common/ErrorBoundary';

/** A component that throws on render to trigger the ErrorBoundary. */
function ThrowingComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test explosion');
  }
  return <div>Child content</div>;
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    // Suppress React error boundary console noise during tests.
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <div>Hello world</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText('Hello world')).toBeInTheDocument();
  });

  it('renders default error UI when a child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('Test explosion')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try Again' })).toBeInTheDocument();
  });

  it('renders custom fallback when provided and child throws', () => {
    render(
      <ErrorBoundary fallback={<div>Custom error fallback</div>}>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Custom error fallback')).toBeInTheDocument();
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
  });

  it('recovers when Try Again is clicked', async () => {
    const user = userEvent.setup();

    // We need a stateful wrapper to control the throw behavior.
    let shouldThrow = true;
    function Wrapper() {
      if (shouldThrow) {
        throw new Error('Recoverable error');
      }
      return <div>Recovered content</div>;
    }

    const { rerender } = render(
      <ErrorBoundary>
        <Wrapper />
      </ErrorBoundary>,
    );

    // Error UI should be visible
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();

    // Fix the error condition before clicking Try Again
    shouldThrow = false;

    await user.click(screen.getByRole('button', { name: 'Try Again' }));

    // After reset, the boundary tries rendering children again.
    // We need to rerender to provide the non-throwing component.
    rerender(
      <ErrorBoundary>
        <Wrapper />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Recovered content')).toBeInTheDocument();
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
  });

  it('displays the error message from the thrown error', () => {
    function SpecificError(): React.ReactNode {
      throw new Error('Database connection failed');
    }

    render(
      <ErrorBoundary>
        <SpecificError />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Database connection failed')).toBeInTheDocument();
  });

  it('does not show the error UI for non-throwing children', () => {
    render(
      <ErrorBoundary>
        <div>Safe content</div>
      </ErrorBoundary>,
    );

    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Try Again' })).not.toBeInTheDocument();
  });

  // Regression test for the actual production gap: AppLayout used to have exactly one
  // ErrorBoundary, wrapping the *entire* app in main.tsx. A crash on any single page (e.g.
  // Sources) replaced the whole app — sidebar, navigation, everything — with the generic
  // error screen, leaving no way to even click to a different, working page. AppLayout now
  // wraps only the routed <Outlet/> in its own ErrorBoundary keyed on the current path, so
  // navigating away from a broken page gets a fresh boundary instead of the stale error UI
  // persisting after the route (and therefore the rendered page) has already changed.
  it('a fresh key (as AppLayout supplies per-route) resets the boundary on navigation, not a stale error screen', () => {
    function Page({ path }: { path: string }) {
      if (path === '/broken') throw new Error('This page crashed');
      return <div>Contents of {path}</div>;
    }

    const { rerender } = render(
      <ErrorBoundary key="/broken">
        <Page path="/broken" />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();

    // Simulate navigating to a different, healthy route — AppLayout re-renders with a new
    // key, which React treats as a brand-new element and remounts rather than reusing the
    // instance still holding hasError: true.
    rerender(
      <ErrorBoundary key="/dashboard">
        <Page path="/dashboard" />
      </ErrorBoundary>,
    );

    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
    expect(screen.getByText('Contents of /dashboard')).toBeInTheDocument();
  });
});
