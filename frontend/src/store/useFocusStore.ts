import { create } from 'zustand';

/**
 * Which job the operator is currently looking at, independent of which page they're on.
 *
 * The floating ATS widget (mounted once at the app shell, alongside CommandPalette and
 * InterventionModal) reads this to know which job's résumé recommendation to show. Set by
 * JobDrawer whenever it opens a job; left as-is when the drawer closes, so the widget keeps
 * showing the last-viewed job's recommendation rather than going blank the moment the
 * operator dismisses the drawer to go compare notes elsewhere.
 */
interface FocusStoreState {
  focusedJobId: string | null;
  focusedJobTitle: string;
  setFocusedJob: (jobId: string, title: string) => void;
  clearFocusedJob: () => void;
}

export const useFocusStore = create<FocusStoreState>((set) => ({
  focusedJobId: null,
  focusedJobTitle: '',
  setFocusedJob: (jobId, title) => set({ focusedJobId: jobId, focusedJobTitle: title }),
  clearFocusedJob: () => set({ focusedJobId: null, focusedJobTitle: '' }),
}));
