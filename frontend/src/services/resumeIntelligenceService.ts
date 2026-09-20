import api, { LLM_CALL_TIMEOUT_MS } from './api';
import type {
  ApplicationResumeVersionOut,
  ChangeDecision,
  CommitTailorResponse,
  CreateBranchRequest,
  MarketSignalsResponse,
  ResumeBranchDetail,
  ResumeBranchSummary,
  ResumeContent,
  ResumeIntelligenceOverview,
  ResumeVersionDetail,
  ResumeVersionSummary,
  TailorResponse,
  VersionDiff,
} from '@/types/resumeIntelligence';

const BASE = '/resume-intelligence';

export async function getOverview(): Promise<ResumeIntelligenceOverview> {
  const { data } = await api.get<ResumeIntelligenceOverview>(`${BASE}/overview`);
  return data;
}

export async function getMaster(): Promise<ResumeVersionDetail> {
  const { data } = await api.get<ResumeVersionDetail>(`${BASE}/master`);
  return data;
}

export async function updateMaster(content: ResumeContent, commitMessage: string): Promise<ResumeVersionDetail> {
  const { data } = await api.put<ResumeVersionDetail>(`${BASE}/master`, {
    content, commit_message: commitMessage,
  });
  return data;
}

export async function listMasterVersions(): Promise<ResumeVersionDetail[]> {
  const { data } = await api.get<ResumeVersionDetail[]>(`${BASE}/master/versions`);
  return data;
}

export async function listBranches(): Promise<ResumeBranchSummary[]> {
  const { data } = await api.get<ResumeBranchSummary[]>(`${BASE}/branches`);
  return data;
}

export async function createBranch(request: CreateBranchRequest): Promise<ResumeBranchSummary> {
  const { data } = await api.post<ResumeBranchSummary>(`${BASE}/branches`, request);
  return data;
}

export async function getBranch(branchId: string): Promise<ResumeBranchDetail> {
  const { data } = await api.get<ResumeBranchDetail>(`${BASE}/branches/${branchId}`);
  return data;
}

export async function deleteBranch(branchId: string): Promise<void> {
  await api.delete(`${BASE}/branches/${branchId}`);
}

export async function listBranchVersions(branchId: string): Promise<ResumeVersionDetail[]> {
  const { data } = await api.get<ResumeVersionDetail[]>(`${BASE}/branches/${branchId}/versions`);
  return data;
}

export async function getMarketSignals(branchId: string, force = false): Promise<MarketSignalsResponse> {
  const { data } = await api.get<MarketSignalsResponse>(`${BASE}/branches/${branchId}/market-signals`, {
    params: force ? { force: true } : undefined,
  });
  return data;
}

export async function getVersion(versionId: string): Promise<ResumeVersionDetail> {
  const { data } = await api.get<ResumeVersionDetail>(`${BASE}/versions/${versionId}`);
  return data;
}

export async function diffVersions(fromId: string, toId: string): Promise<VersionDiff> {
  const { data } = await api.get<VersionDiff>(`${BASE}/versions/diff`, {
    params: { from_id: fromId, to_id: toId },
  });
  return data;
}

export async function restoreVersion(versionId: string, commitMessage = ''): Promise<ResumeVersionSummary> {
  const { data } = await api.post<ResumeVersionSummary>(`${BASE}/versions/${versionId}/restore`, {
    commit_message: commitMessage,
  });
  return data;
}

export async function tailorJob(jobId: string, branchId?: string): Promise<TailorResponse> {
  const { data } = await api.post<TailorResponse>(`${BASE}/tailor`, {
    job_id: jobId, branch_id: branchId ?? null,
  }, { timeout: LLM_CALL_TIMEOUT_MS });
  return data;
}

export async function commitTailor(
  analysisId: string, decisions: ChangeDecision[], commitMessage = '',
): Promise<CommitTailorResponse> {
  const { data } = await api.post<CommitTailorResponse>(`${BASE}/tailor/${analysisId}/commit`, {
    decisions, commit_message: commitMessage,
  });
  return data;
}

export async function getApplicationResumeVersion(applicationId: string): Promise<ApplicationResumeVersionOut> {
  const { data } = await api.get<ApplicationResumeVersionOut>(`${BASE}/applications/${applicationId}/resume-version`);
  return data;
}
