/** Top-level dashboard statistics. */
export interface DashboardStats {
  total_jobs_found: number;
  total_applications: number;
  applications_pending: number;
  applications_applied: number;
  applications_interview: number;
  applications_rejected: number;
  applications_offer: number;
  applications_failed: number;
  /** Agent activity right now. */
  applications_queued: number;
  applications_applying: number;
  /** Submissions actually sent, counted on applied_at — a queued row is not one sent. */
  submitted_today: number;
  submitted_this_week: number;
  avg_ats_score: number;
  total_llm_cost_usd: number;
  /** Since local midnight — distinct from total_jobs_found's all-time count. */
  jobs_found_today: number;
  /** Distinct vacancies after cross-source dedup. */
  unique_jobs: number;
  jobs_by_source: Record<string, number>;
  /** Register-confirmed only — the strongest sponsorship tier. */
  sponsor_confirmed_jobs: number;
  /** Agent-produced résumés (tailored/optimized) — excludes the uploaded base CV. */
  cvs_generated: number;
  /** ISO timestamp, or null if the sponsor register has never been fetched. */
  sponsor_register_last_refreshed: string | null;
}

/** A single stage in the application funnel. */
export interface ApplicationFunnelData {
  stage: string;
  count: number;
}

/** ATS score histogram bucket. */
export interface ATSScoreDistribution {
  range_label: string;
  count: number;
}

/** LLM provider usage aggregation. */
export interface LLMUsageStats {
  provider: string;
  model: string;
  total_requests: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number;
}

/** Daily activity timeline entry. */
export interface TimelineEntry {
  date: string;
  applications_created: number;
  applications_applied: number;
  jobs_found: number;
}
