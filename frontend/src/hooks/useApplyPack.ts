import { useQuery } from '@tanstack/react-query';

import api from '@/services/api';
import type { ApplyPack } from '@/types/applyPack';

async function getApplyPack(appId: string): Promise<ApplyPack> {
  const { data } = await api.get<ApplyPack>(`/applications/${encodeURIComponent(appId)}/pack`);
  return data;
}

/** The application pack, fetched only when the panel is opened. */
export function useApplyPack(appId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['applications', 'pack', appId],
    queryFn: () => getApplyPack(appId),
    enabled,
    staleTime: 60_000,
  });
}
