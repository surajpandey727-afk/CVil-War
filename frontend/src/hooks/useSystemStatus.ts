import { useQuery } from '@tanstack/react-query';

import { getSystemStatus } from '@/services/systemService';

/** Polls the system status so the connection widget stays live without a websocket. */
export function useSystemStatus() {
  return useQuery({
    queryKey: ['system', 'status'],
    queryFn: getSystemStatus,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}
