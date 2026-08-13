/** Job-source catalogue types. Corresponds to `backend/app/api/v1/sources.py`. */

export type SourceHealth = 'live' | 'degraded' | 'auth_required' | 'not_implemented';

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
