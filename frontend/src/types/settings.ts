export interface WorkExperience {
  title: string;
  company: string;
  start_date: string;
  end_date: string;
  description: string;
  responsibilities: string[];
}

export interface Education {
  degree: string;
  institution: string;
  graduation_year: string;
  gpa?: string;
}

export interface CandidateProfile {
  full_name: string;
  email: string;
  phone: string;
  location: string;
  linkedin_url: string;
  github_url: string;
  summary: string;
  skills: string[];
  experience: WorkExperience[];
  education: Education[];
  certifications: string[];
}

export type RoleFamilyKey = 'product' | 'engineering' | 'architecture' | 'data';

/** One targeted role title. Corresponds to the backend `RoleTargetSchema`. */
export interface RoleTargetRecord {
  title: string;
  fit: number;
  why: string;
  family: RoleFamilyKey;
  active: boolean;
}

/** Résumé-selection rule. Evaluated in order; first match wins. */
export interface ResumeRule {
  title_pattern: string;
  company_pattern: string;
  resume_id: string;
  label: string;
}

export interface RunWindow {
  days: string[];
  start: string;
  end: string;
  timezone: string;
}

/**
 * The auto-apply policy. Corresponds to the backend `AutomationPolicy` -- the model the rule
 * engine evaluates, not a separate settings shape that happens to resemble it.
 *
 * The index signature is what makes the automation screen schema-driven: controls are
 * rendered from the rule catalogue the backend serves, and each one reads and writes
 * `policy[rule.field_name]`. A clause added to the backend catalogue reaches the UI without
 * a change to this file. The named fields below are those other screens reference directly.
 */
export interface AutomationSettings {
  [field: string]: unknown;
  version?: number;
  /** Master stop (policy 4.2). Everything stays queued; nothing is submitted. */
  paused: boolean;
  require_review_above_salary_k: number;
  review_first_run_per_source: boolean;
  /** 0-1, same scale as `Settings.min_ats_score`. */
  min_ats_score: number;
  min_salary_k: number;
  seniority: string[];
  blocked_companies: string[];
  max_per_day: number;
  max_per_hour: number;
  min_seconds_between: number;
  max_per_company_per_week: number;
  reapply_cooldown_days: number;
  default_resume_id: string | null;
  resume_rules: ResumeRule[];
  cover_letters: boolean;
  cover_letter_tone: 'direct' | 'warm' | 'formal' | 'technical';
  retry_failed: boolean;
  max_retries: number;
  circuit_breaker_failures: number;
  pause_on_captcha: boolean;
  email_fallback: boolean;
  notify_each_outcome: boolean;
  retain_documents_days: number;
  disclose_ai_assistance: boolean;
  run_window: RunWindow;
  enabled_sources: string[];
}

export const DEFAULT_AUTOMATION: AutomationSettings = {
  paused: false,
  require_review_above_salary_k: 120,
  review_first_run_per_source: true,
  min_ats_score: 0.75,
  min_salary_k: 0,
  seniority: [],
  blocked_companies: [],
  max_per_day: 20,
  max_per_hour: 5,
  min_seconds_between: 90,
  max_per_company_per_week: 2,
  reapply_cooldown_days: 90,
  default_resume_id: null,
  resume_rules: [],
  cover_letters: true,
  cover_letter_tone: 'direct',
  retry_failed: true,
  max_retries: 3,
  circuit_breaker_failures: 3,
  pause_on_captcha: true,
  email_fallback: true,
  notify_each_outcome: true,
  retain_documents_days: 0,
  disclose_ai_assistance: false,
  run_window: { days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'], start: '08:00', end: '19:00', timezone: 'Europe/London' },
  enabled_sources: [],
};

/** How one policy field is edited. Mirrors the backend `ControlSpec`. */
export type PolicyControlKind =
  | 'toggle' | 'integer' | 'percent' | 'money_k' | 'days' | 'seconds'
  | 'choice' | 'multi_choice' | 'text_list' | 'time' | 'weekdays' | 'locked';

export interface PolicyControl {
  kind: PolicyControlKind;
  min: number | null;
  max: number | null;
  step: number | null;
  unit: string;
  options: string[];
}

/** Where a clause is enforced. `gate` refuses submissions; `behaviour` only changes them. */
export type PolicyEnforcement = 'gate' | 'elsewhere' | 'behaviour';

export type PolicyVerdict = 'allow' | 'hold' | 'escalate' | 'block';

/** One clause of the automation policy, as served by the backend catalogue. */
export interface PolicyRuleInfo {
  id: string;
  /** Reference into `docs/AUTOMATION_POLICY.md`, e.g. "S2.1". */
  clause: string;
  title: string;
  rationale: string;
  enforcement: PolicyEnforcement;
  verdict: PolicyVerdict;
  locked: boolean;
  control: PolicyControl;
  field_name: string;
  enforced_by: string;
  value: unknown;
}

export interface PolicyGroup {
  id: string;
  title: string;
  rules: PolicyRuleInfo[];
}

export interface PolicyCatalogue {
  policy_version: number;
  document: string;
  groups: PolicyGroup[];
  policy: AutomationSettings;
}

export interface PolicyPreviewItem {
  application_id: string;
  job_title: string;
  company: string;
  verdict: PolicyVerdict;
  reasons: string[];
  rule_ids: string[];
}

/** A dry run of an unsaved policy against everything currently queued. */
export interface PolicyPreview {
  evaluated: number;
  allow: number;
  hold: number;
  escalate: number;
  block: number;
  items: PolicyPreviewItem[];
}

/**
 * Current user settings.
 * Corresponds to the backend `SettingsResponse` Pydantic schema.
 */
export interface Settings {
  apply_mode: string;
  min_ats_score: number;
  max_parallel: number;
  preferred_provider: string;
  platforms_enabled: string[];
  candidate_profile: CandidateProfile;
  role_targets: RoleTargetRecord[];
  automation: AutomationSettings;
}

/** Alias matching the backend schema name `SettingsResponse`. */
export type SettingsResponse = Settings;

/** Request to update user settings. Only provided fields are changed. */
export interface SettingsUpdate {
  apply_mode?: string;
  min_ats_score?: number;
  max_parallel?: number;
  preferred_provider?: string;
  platforms_enabled?: string[];
  candidate_profile?: CandidateProfile;
  role_targets?: RoleTargetRecord[];
  automation?: AutomationSettings;
}

/** Status of a configured LLM provider. */
export interface LLMProviderStatus {
  provider: string;
  configured: boolean;
  model: string;
  is_primary: boolean;
}
