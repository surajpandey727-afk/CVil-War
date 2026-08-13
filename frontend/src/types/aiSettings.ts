/**
 * The AI control plane. Mirrors the backend `AICatalogue` / `AIUsageReport` schemas.
 *
 * Two flags carry meaning that emptiness cannot: `reachable` separates "cannot reach the
 * gateway" from "the gateway offers nothing", and `recorded` separates "no calls in this
 * period" from a measured row of zeroes. Both pairs need different words in the UI.
 *
 * `null` metadata means the gateway did not report it. It is never defaulted — a plausible
 * context limit is the kind of number an operator plans around.
 */

export interface AIModelInfo {
  id: string;
  provider: string;
  /** Normalised: tool_calling, vision, reasoning, temperature, effort_tiers. */
  capabilities: string[];
  context_length: number | null;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  is_default: boolean;
}

export interface AIProviderInfo {
  id: string;
  model_count: number;
  models: AIModelInfo[];
}

export interface AICatalogue {
  reachable: boolean;
  /** Verbatim when unreachable — "connection refused" and "401" need different fixes. */
  error: string | null;
  base_url: string;
  provider_count: number;
  model_count: number;
  default_model: string;
  /** False when the configured default names a model the gateway does not list. */
  default_model_available: boolean;
  providers: AIProviderInfo[];
}

export interface AIUsageBreakdown {
  key: string;
  total_tokens: number;
  cost_usd: number;
  requests: number;
}

export type AIUsagePeriod = 'today' | '7d' | '30d' | 'all';

export interface AIUsageReport {
  period: string;
  /** False when no calls were recorded in the window. */
  recorded: boolean;
  requests: number;
  errors: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  by_provider: AIUsageBreakdown[];
  by_model: AIUsageBreakdown[];
  by_purpose: AIUsageBreakdown[];
  top_model: string | null;
  top_purpose: string | null;
}
