import api from './api';
import type { SkillAggregateResponse, SkillScoreResponse } from '@/types/skills';

/** Role titles with a curated skill profile — the suggested selections. */
export async function listSkillRoles(): Promise<string[]> {
  const { data } = await api.get<string[]>('/skills/roles');
  return data;
}

/** Aggregate the in-demand skills across the selected roles. */
export async function aggregateSkills(titles: string[]): Promise<SkillAggregateResponse> {
  const { data } = await api.post<SkillAggregateResponse>('/skills/aggregate', { titles });
  return data;
}

/** Score a résumé against the skills the selected roles want. */
export async function scoreResumeSkills(
  resumeId: string,
  titles: string[],
): Promise<SkillScoreResponse> {
  const { data } = await api.post<SkillScoreResponse>('/skills/score', {
    resume_id: resumeId,
    titles,
  });
  return data;
}
