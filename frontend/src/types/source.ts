/** Job-source catalogue types. Corresponds to `backend/app/api/v1/sources.py`.
 *
 *  `SourceHealth` must mirror `app.core.job_discovery.source_registry.SourceHealth` exactly —
 *  it previously listed only 4 of the backend's 7 values. `rate_limited`, `interactive_available`
 *  and `unavailable` were missing, so any source in one of those states made `HEALTH_META[health]`
 *  return `undefined` and crash `SourcesPage` outright the moment a source like Civil Service
 *  Jobs (browser-only, `interactive_available`) reached the catalogue — the whole page failed to
 *  render rather than just that one card. */

export type SourceHealth =
  | 'live'
  | 'degraded'
  | 'auth_required'
  | 'rate_limited'
  | 'interactive_available'
  | 'unavailable'
  | 'not_implemented';

export interface SourceRecord {
  key: string;
  label: string;
  domain: string;
  tier: string;
  implemented: boolean;
  health: SourceHealth;
  note: string;
}

export interface SourceTierRecord {
  id: string;
  name: string;
  note: string;
  sources: SourceRecord[];
}

export interface SourceCatalogue {
  tiers: SourceTierRecord[];
  /** Keys that can return results right now — the safe default for a search fan-out. */
  live_keys: string[];
  total: number;
}
