import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as service from '@/services/resumeIntelligenceService';
import type { ChangeDecision, CreateBranchRequest, ResumeContent } from '@/types/resumeIntelligence';

const RI_KEY = ['resume-intelligence'] as const;

export function useResumeIntelligenceOverview() {
  return useQuery({ queryKey: [...RI_KEY, 'overview'], queryFn: service.getOverview });
}

export function useMaster() {
  return useQuery({ queryKey: [...RI_KEY, 'master'], queryFn: service.getMaster });
}

export function useUpdateMaster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ content, commitMessage }: { content: ResumeContent; commitMessage: string }) =>
      service.updateMaster(content, commitMessage),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: RI_KEY });
    },
  });
}

export function useMasterVersions() {
  return useQuery({ queryKey: [...RI_KEY, 'master-versions'], queryFn: service.listMasterVersions });
}

export function useBranches() {
  return useQuery({ queryKey: [...RI_KEY, 'branches'], queryFn: service.listBranches });
}

export function useCreateBranch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateBranchRequest) => service.createBranch(request),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: RI_KEY });
    },
  });
}

export function useBranch(branchId: string | undefined) {
  return useQuery({
    queryKey: [...RI_KEY, 'branch', branchId],
    queryFn: () => service.getBranch(branchId!),
    enabled: !!branchId,
  });
}

export function useDeleteBranch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (branchId: string) => service.deleteBranch(branchId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: RI_KEY });
    },
  });
}

export function useBranchVersions(branchId: string | undefined) {
  return useQuery({
    queryKey: [...RI_KEY, 'branch-versions', branchId],
    queryFn: () => service.listBranchVersions(branchId!),
    enabled: !!branchId,
  });
}

export function useMarketSignals(branchId: string | undefined) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: [...RI_KEY, 'market-signals', branchId],
    queryFn: () => service.getMarketSignals(branchId!),
    enabled: !!branchId,
  });
  const refresh = useMutation({
    mutationFn: () => service.getMarketSignals(branchId!, true),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...RI_KEY, 'market-signals', branchId] });
      void qc.invalidateQueries({ queryKey: [...RI_KEY, 'branch', branchId] });
    },
  });
  return { ...query, refresh };
}

export function useVersion(versionId: string | undefined) {
  return useQuery({
    queryKey: [...RI_KEY, 'version', versionId],
    queryFn: () => service.getVersion(versionId!),
    enabled: !!versionId,
  });
}

export function useVersionDiff(fromId: string | undefined, toId: string | undefined) {
  return useQuery({
    queryKey: [...RI_KEY, 'diff', fromId, toId],
    queryFn: () => service.diffVersions(fromId!, toId!),
    enabled: !!fromId && !!toId,
  });
}

export function useRestoreVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ versionId, commitMessage }: { versionId: string; commitMessage?: string }) =>
      service.restoreVersion(versionId, commitMessage),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: RI_KEY });
    },
  });
}

/**
 * Fires the costly LLM call — only ever when the caller has an explicit job to tailor
 * against (never on a passive page view). Modelled as a query, not a mutation: a
 * `useMutation` fired from an effect on mount is a known StrictMode/remount hazard in
 * TanStack Query — the in-flight promise's result can land on an observer nothing is
 * subscribed to anymore, leaving the UI stuck "pending" forever even though the request
 * actually succeeded (reproduced live: the network call completes and the backend logs
 * success, but the component never re-renders). `useQuery` doesn't have this failure mode
 * — it's keyed and cache-backed, so a StrictMode remount re-attaches to the same in-flight
 * request instead of orphaning it. `enabled` still gates it on having both ids, so it never
 * fires until the caller explicitly navigates here with a job.
 */
export function useTailorJob(jobId: string | undefined, branchId: string | undefined) {
  return useQuery({
    queryKey: [...RI_KEY, 'tailor', jobId, branchId],
    queryFn: () => service.tailorJob(jobId as string, branchId),
    enabled: !!jobId && !!branchId,
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

export function useCommitTailor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ analysisId, decisions, commitMessage }: {
      analysisId: string; decisions: ChangeDecision[]; commitMessage?: string;
    }) => service.commitTailor(analysisId, decisions, commitMessage),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: RI_KEY });
    },
  });
}

export function useApplicationResumeVersion(applicationId: string | undefined) {
  return useQuery({
    queryKey: [...RI_KEY, 'application-version', applicationId],
    queryFn: () => service.getApplicationResumeVersion(applicationId!),
    enabled: !!applicationId,
  });
}
