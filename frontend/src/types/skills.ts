/** Mirrors backend app/schemas/skills.py. Scores are 0–1 (multiply by 100 to display). */

export interface AggregatedSkill {
  key: string;
  label: string;
  category: string;
  /** Summed weight across the selected roles that want this skill. */
  demand: number;
  /** How many of the selected roles want it. */
  roles_wanting: number;
  must_have: boolean;
  /** An ATS keyword — a term applicant-tracking screens on literally. */
  ats: boolean;
  /** Live posting frequency when the corpus held jobs, else null (never 0 for "not looked"). */
  corpus_count: number | null;
}

export interface SkillAggregateResponse {
  titles: string[];
  categories: string[];
  skills: AggregatedSkill[];
  corpus_used: boolean;
}

export interface SkillHit {
  key: string;
  label: string;
  category: string;
  demand: number;
  roles_wanting: number;
  must_have: boolean;
  ats: boolean;
  present: boolean;
  matched_form: string | null;
}

export type SkillBand = 'strong' | 'decent' | 'gap';

export interface SkillScoreResponse {
  resume_id: string;
  resume_name: string;
  titles: string[];
  /** 0–1 weighted coverage. */
  score: number;
  /** 0–1 coverage of must-have skills only. */
  must_have_score: number;
  band: SkillBand;
  matched_count: number;
  total_count: number;
  hits: SkillHit[];
  top_to_add: SkillHit[];
}
