import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as service from '@/services/communicationService';

const COMMS_KEY = ['communications'] as const;

export function useGmailStatus() {
  return useQuery({
    queryKey: [...COMMS_KEY, 'gmail-status'],
    queryFn: service.getGmailStatus,
  });
}

export function useDisconnectGmail() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: service.disconnectGmail,
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...COMMS_KEY, 'gmail-status'] }),
  });
}

export function useApolloStatus() {
  return useQuery({
    queryKey: [...COMMS_KEY, 'apollo-status'],
    queryFn: service.getApolloStatus,
  });
}

export function useInboxSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: service.runInboxSync,
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...COMMS_KEY, 'list'] }),
  });
}

export function useCommunications(unmatchedOnly: boolean, page = 1, pageSize = 30) {
  return useQuery({
    queryKey: [...COMMS_KEY, 'list', unmatchedOnly, page, pageSize],
    queryFn: () => service.listCommunications(unmatchedOnly, page, pageSize),
  });
}

export function useLinkApplication() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ eventId, applicationId }: { eventId: string; applicationId: string }) =>
      service.linkApplication(eventId, applicationId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: [...COMMS_KEY, 'list'] }),
  });
}

export function useLogRecruiterContact() {
  return useMutation({
    mutationFn: ({
      applicationId,
      ...request
    }: { applicationId: string } & Parameters<typeof service.logRecruiterContact>[1]) =>
      service.logRecruiterContact(applicationId, request),
  });
}
