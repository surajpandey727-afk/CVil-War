import { useQuery } from '@tanstack/react-query';

import * as sourceService from '@/services/sourceService';
import { HEALTH_META, SOURCE_TIERS, sourcesInTier } from '@/lib/sources';
import type { SourceCatalogue } from '@/types/source';

/** Static catalogue used until the server responds, and if the endpoint is unavailable. */
const FALLBACK: SourceCatalogue = {
  tiers: SOURCE_TIERS.map((t) => ({
    id: t.id,
    name: t.name,
    note: t.note,
    sources: sourcesInTier(t.id).map((s) => ({
      key: s.key,
      label: s.label,
      domain: s.domain,
      tier: s.tier,
      implemented: s.implemented,
      health: s.health,
      note: s.note ?? '',
    })),
  })),
  live_keys: [],
  total: 0,
};
FALLBACK.live_keys = FALLBACK.tiers.flatMap((t) => t.sources.filter((s) => s.health === 'live').map((s) => s.key));
FALLBACK.total = FALLBACK.tiers.reduce((n, t) => n + t.sources.length, 0);

/**
 * The source catalogue with live health.
 *
 * Falls back to the static catalogue in `lib/sources` rather than rendering an empty rail:
 * a source list is navigation, and an operator staring at nothing cannot tell a dead endpoint
 * from a genuinely empty configuration. `isFallback` says which one they are looking at.
 */
export function useSources() {
  const query = useQuery({
    queryKey: ['sources', 'catalogue'],
    queryFn: () => sourceService.getSourceCatalogue(),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  return {
    ...query,
    catalogue: query.data ?? FALLBACK,
    isFallback: !query.data,
  };
}

export { HEALTH_META };
