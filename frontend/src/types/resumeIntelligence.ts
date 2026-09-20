/** Resume Intelligence — mirrors backend/app/schemas/resume_intelligence.py exactly. */

export interface Achievement {
  id: string;
  text: string;
  technologies: string[];
  evidence: string;
}

export interface ExperienceEntry {
  id: string;
  title: string;
  company: string;
  location: string;
  start_date: string;
  end_date: string;
  achievements: Achievement[];
}

export interface ProjectEntry {
  id: string;
  name: string;
  description: string;
  technologies: string[];
  evidence: string;
  link: string;
}

export interface EducationEntry {
  degree: string;
  institution: string;
  graduation_year: string;
  gpa: string | null;
}

export interface ResumeHeader {
  full_name: string;
  email: string;
  phone: string;
  location: string;
  linkedin_url: string;
  github_url: string;
}

export interface ResumeContent {
  header: ResumeHeader;
  summary: string;
  experience: ExperienceEntry[];
  projects: ProjectEntry[];
  education: EducationEntry[];
  skills: string[];
  certifications: string[];
  additional: string[];
}

export type ResumeVersionSource = 'initial' | 'user_edit' | 'ai_suggestion' | 'restored';
export type ResumeChangeType =
  | 'added' | 'removed' | 'modified' | 'reordered' | 'rephrased'
  | 'role_positioning' | 'ats_alignment' | 'market_signal' | 'user_edit' | 'ai_suggestion' | 'restored';
export type ResumeChangeStatus = 'proposed' | 'accepted' | 'rejected';
export type RoleFamily = 'product' | 'engineering' | 'architecture' | 'data';

export interface ResumeChangeOut {
  id: string;
  change_type: ResumeChangeType;
  section: string;
  before_text: string | null;
  after_text: string | null;
  reason: string;
  source_job_id: string | null;
  evidence: string | null;
  status: ResumeChangeStatus;
  created_at: string;
}

export interface ResumeVersionSummary {
  id: string;
  branch_id: string | null;
  version_label: string;
  sequence: number;
  source: ResumeVersionSource;
  commit_message: string;
  content_hash: string;
  created_at: string;
}

export interface ResumeVersionDetail extends ResumeVersionSummary {
  content: ResumeContent;
  changes: ResumeChangeOut[];
}

export interface ResumeBranchSummary {
  id: string;
  role_name: string;
  role_family: RoleFamily;
  description: string;
  current_version: ResumeVersionSummary | null;
  market_signals_computed_at: string | null;
}

export interface SkillSignal {
  frequency: number;
  matched_jobs: number;
  total_jobs: number;
}

export interface ResumeBranchDetail extends ResumeBranchSummary {
  current_content: ResumeContent | null;
  market_signals: Record<string, SkillSignal> | null;
}

export interface ResumeIntelligenceOverview {
  master_version: ResumeVersionSummary | null;
  branches: ResumeBranchSummary[];
  recent_changes_count: number;
}

export interface CreateBranchRequest {
  role_name: string;
  role_family: RoleFamily;
  description?: string;
}

export interface UpdateMasterRequest {
  content: ResumeContent;
  commit_message: string;
}

export interface VersionDiffEntry {
  section: string;
  path: string;
  before?: string | null;
  after?: string | null;
}

export interface VersionDiff {
  from_version_id: string;
  to_version_id: string;
  added: VersionDiffEntry[];
  removed: VersionDiffEntry[];
  modified: VersionDiffEntry[];
}

export interface MarketSignalsResponse {
  branch_id: string;
  signals: Record<string, SkillSignal>;
  matched_jobs: number;
  total_jobs_scanned: number;
  computed_at: string;
}

export interface TitleAnalysisOut {
  current_title: string;
  target_title: string;
  relationship: string;
  shared_experience: string[];
  positioning_opportunity: string;
}

export interface ProposedChangeOut {
  id: string;
  change_type: ResumeChangeType;
  section: string;
  before_text: string | null;
  after_text: string | null;
  reason: string;
  evidence: string | null;
}

export interface TailorResponse {
  analysis_id: string;
  branch_id: string;
  branch_role_name: string;
  base_version_id: string;
  matched: Record<string, string>;
  partial: Record<string, string>;
  missing: Record<string, string>;
  ats_alignment_pct: number | null;
  role_fit_notes: string;
  positioning_notes: string;
  title_analysis: TitleAnalysisOut | null;
  proposed_changes: ProposedChangeOut[];
}

export interface ChangeDecision {
  change_id: string;
  decision: 'accept' | 'reject' | 'edit';
  edited_after_text?: string | null;
}

export interface CommitTailorRequest {
  decisions: ChangeDecision[];
  commit_message?: string;
}

export interface CommitTailorResponse {
  version: ResumeVersionSummary;
  accepted_count: number;
  rejected_count: number;
  ats_alignment_before: number | null;
  ats_alignment_after: number | null;
}

export interface ApplicationResumeVersionOut {
  application_id: string;
  resume_version_id: string | null;
  version_label: string | null;
  branch_role_name: string | null;
}
