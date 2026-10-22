import { useMutation, useQuery } from '@tanstack/react-query';

import * as skillService from '@/services/skillService';

/** The curated role titles to offer as selectable chips. */
export function useSkillRoles() {
  return useQuery({
    queryKey: ['skills', 'roles'],
    queryFn: skillService.listSkillRoles,
    staleTime: 60 * 60 * 1000, // the catalogue is static within a session
  });
}

/** Aggregated demand for a set of roles. Enabled only once at least one role is selected. */
export function useAggregatedSkills(titles: string[]) {
  return useQuery({
    queryKey: ['skills', 'aggregate', [...titles].sort()],
    queryFn: () => skillService.aggregateSkills(titles),
    enabled: titles.length > 0,
    staleTime: 5 * 60 * 1000,
  });
}

/** Score a résumé on demand (a mutation — the user clicks "Run match"). */
export function useScoreResumeSkills() {
  return useMutation({
    mutationFn: ({ resumeId, titles }: { resumeId: string; titles: string[] }) =>
      skillService.scoreResumeSkills(resumeId, titles),
  });
}
