import api from './api';
import type {
  ApolloStatus,
  CommunicationEventListResponse,
  GmailStatus,
  InboxSyncResult,
  LogRecruiterContactRequest,
  LogRecruiterContactResponse,
} from '@/types/communications';

export async function getGmailStatus(): Promise<GmailStatus> {
  const { data } = await api.get<GmailStatus>('/communications/gmail/status');
  return data;
}

export async function disconnectGmail(): Promise<void> {
  await api.delete('/communications/gmail');
}

export async function getApolloStatus(): Promise<ApolloStatus> {
  const { data } = await api.get<ApolloStatus>('/communications/apollo/status');
  return data;
}

export async function runInboxSync(): Promise<InboxSyncResult> {
  const { data } = await api.post<InboxSyncResult>('/communications/inbox-sync');
  return data;
}

export async function listCommunications(
  unmatchedOnly = false,
  page = 1,
  pageSize = 30,
): Promise<CommunicationEventListResponse> {
  const { data } = await api.get<CommunicationEventListResponse>('/communications/', {
    params: { unmatched_only: unmatchedOnly, page, page_size: pageSize },
  });
  return data;
}

export async function linkApplication(eventId: string, applicationId: string) {
  const { data } = await api.post(`/communications/${eventId}/link-application`, {
    application_id: applicationId,
  });
  return data;
}

/** Logs a recruiter contact to Apollo and the application's own timeline. Lives under
 *  /applications, not /communications — it is scoped to one application, matching the
 *  backend route. */
export async function logRecruiterContact(
  applicationId: string,
  request: LogRecruiterContactRequest,
): Promise<LogRecruiterContactResponse> {
  const { data } = await api.post<LogRecruiterContactResponse>(
    `/applications/${applicationId}/log-recruiter-contact`,
    request,
  );
  return data;
}
