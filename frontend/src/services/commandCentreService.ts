import api from '@/services/api';
import type {
  ActionQueue,
  ApplicationTimeline,
  CommandCentreSummary,
} from '@/types/commandCentre';

/** The command centre's read surface: what needs doing, and how each application got here. */
export const commandCentreService = {
  async summary(): Promise<CommandCentreSummary> {
    const { data } = await api.get<CommandCentreSummary>('/command-centre/summary');
    return data;
  },

  async queue(): Promise<ActionQueue> {
    const { data } = await api.get<ActionQueue>('/command-centre/queue');
    return data;
  },

  async timeline(applicationId: string): Promise<ApplicationTimeline> {
    const { data } = await api.get<ApplicationTimeline>(
      `/command-centre/applications/${applicationId}/timeline`,
    );
    return data;
  },
};
