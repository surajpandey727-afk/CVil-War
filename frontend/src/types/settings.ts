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

/** Auto-apply policy. Corresponds to the backend `AutomationSettingsSchema`. */
export interface AutomationSettings {
  /** 0–1, same scale as `Settings.min_ats_score`. */
  min_ats_score: number;
  min_salary_k: number;
  seniority: string[];
  blocked_companies: string[];
  default_resume_id: string | null;
  resume_rules: ResumeRule[];
  cover_letters: boolean;
  cover_letter_tone: 'direct' | 'warm' | 'formal' | 'technical';
  retry_failed: boolean;
  max_retries: number;
  pause_on_captcha: boolean;
  email_fallback: boolean;
  notify_each_outcome: boolean;
  run_window: RunWindow;
  enabled_sources: string[];
}

export const DEFAULT_AUTOMATION: AutomationSettings = {
  min_ats_score: 0.75,
  min_salary_k: 0,
  seniority: [],
  blocked_companies: [],
  default_resume_id: null,
  resume_rules: [],
  cover_letters: true,
  cover_letter_tone: 'direct',
  retry_failed: true,
  max_retries: 3,
  pause_on_captcha: true,
  email_fallback: true,
  notify_each_outcome: true,
  run_window: { days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'], start: '08:00', end: '19:00', timezone: 'Europe/London' },
  enabled_sources: [],
};

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
