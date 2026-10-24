import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import Sidebar from './Sidebar';
import Header from './Header';
import CommandPalette from '@/components/ui/CommandPalette';
import InterventionModal from '@/components/applications/InterventionModal';
import FloatingAtsWidget from '@/components/ats/FloatingAtsWidget';
import ErrorBoundary from '@/components/common/ErrorBoundary';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useApplicationEvents } from '@/hooks/useApplicationEvents';
import { useAppStore } from '@/store/useAppStore';
import { useUiStore } from '@/store/useUiStore';

/** App shell — collapsible sidebar + header + scrollable content, per the design system.
 *  The live WebSocket + application-event wiring (unchanged) drives real-time cache updates. */
export default function AppLayout() {
  const { connected, lastMessage } = useWebSocket('/ws');
  const setWsConnected = useAppStore((s) => s.setWsConnected);
  const setPaletteOpen = useUiStore((s) => s.setPaletteOpen);
  const setSidebar = useUiStore((s) => s.setSidebar);
  const location = useLocation();

  useApplicationEvents(lastMessage);

  useEffect(() => {
    setWsConnected(connected);
  }, [connected, setWsConnected]);

  // On a narrow screen the expanded sidebar took the whole width: at 320px the page content
  // was left 18px wide. Collapse it to the icon rail whenever the viewport enters that range;
  // the header toggle still expands it on demand.
  useEffect(() => {
    const narrow = window.matchMedia('(max-width: 900px)');
    const apply = () => { if (narrow.matches) setSidebar(true); };
    apply();
    narrow.addEventListener('change', apply);
    return () => narrow.removeEventListener('change', apply);
  }, [setSidebar]);

  // ⌘K / Ctrl-K opens the command palette from anywhere in the app.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setPaletteOpen]);

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        overflow: 'hidden',
        background: 'var(--bg)',
        color: 'var(--text)',
        fontFamily: 'var(--font)',
        letterSpacing: '-.01em',
      }}
    >
      <Sidebar />
      <div style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <Header />
        <main style={{ flex: '1 1 auto', minHeight: 0, overflowY: 'auto', position: 'relative' }}>
          <div className="app-content" style={{ maxWidth: 1460, margin: '0 auto' }}>
            {/* Scoped to the routed page, not the whole app (main.tsx has that one) — a bug on
                one screen used to blank out the sidebar and every other page along with it,
                leaving no way to navigate away from the crash. Keyed on the path so leaving a
                broken page for a working one gets a fresh boundary instead of the stale error
                UI persisting after the route change. */}
            <ErrorBoundary key={location.pathname}>
              <Outlet />
            </ErrorBoundary>
          </div>
        </main>
      </div>
      <CommandPalette />
      <InterventionModal />
      <FloatingAtsWidget />
    </div>
  );
}
