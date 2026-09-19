import { create } from 'zustand';

/**
 * Which job the operator is currently looking at, independent of which page they're on.
 *
 * The floating ATS widget (mounted once at the app shell, alongside CommandPalette and
 * InterventionModal) reads this to know which job's résumé recommendation to show. Set by
 * JobDrawer whenever it opens a job; left as-is when the drawer closes, so the widget keeps
 * showing the last-viewed job's recommendation rather than going blank the moment the
 * operator dismisses the drawer to go compare notes elsewhere.
 *
 * `openSignal` is a separate concern from `focusedJobId`: focusing a job (e.g. re-rendering a
 * list row) should not by itself yank open a widget the operator deliberately collapsed. Only
 * an explicit "show me this" action — a row's own AI-review trigger — bumps it, and the
 * widget's own effect un-collapses in response. A plain counter rather than a boolean because
 * re-requesting the SAME job (openSignal wouldn't otherwise change) must still re-open it.
 */
interface FocusStoreState {
  focusedJobId: string | null;
  focusedJobTitle: string;
  openSignal: number;
  setFocusedJob: (jobId: string, title: string, opts?: { openWidget?: boolean }) => void;
  clearFocusedJob: () => void;
}

export const useFocusStore = create<FocusStoreState>((set, get) => ({
  focusedJobId: null,
  focusedJobTitle: '',
  openSignal: 0,
  setFocusedJob: (jobId, title, opts) =>
    set({
      focusedJobId: jobId, focusedJobTitle: title,
      openSignal: opts?.openWidget ? get().openSignal + 1 : get().openSignal,
    }),
  clearFocusedJob: () => set({ focusedJobId: null, focusedJobTitle: '' }),
}));
