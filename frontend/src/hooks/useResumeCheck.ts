import { useMutation } from '@tanstack/react-query';

import * as resumeCheckService from '@/services/resumeCheckService';
import type { ResumeCheckRequest } from '@/types/resumeCheck';

/** Run the deterministic check (a mutation — the user clicks "Run check"). */
export function useResumeCheck() {
  return useMutation({
    mutationFn: (body: ResumeCheckRequest) => resumeCheckService.checkResume(body),
  });
}

/** The slow AI review. Fired by the page once the check lands; never blocks it. */
export function useResumeReview() {
  return useMutation({
    mutationFn: (body: ResumeCheckRequest) => resumeCheckService.reviewResume(body),
  });
}
