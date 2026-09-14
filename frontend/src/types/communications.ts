export interface GmailStatus {
  configured: boolean;
  connected: boolean;
  authorize_url: string | null;
}

export interface ApolloStatus {
  configured: boolean;
}

export interface InboxSyncResult {
  fetched: number;
  already_seen: number;
  matched_to_application: number;
  unmatched: number;
  errors: string[];
}

export type CommunicationClassification = 'rejection' | 'interview_invite' | 'reply' | '';

export interface CommunicationEventItem {
  id: string;
  source: string;
  application_id: string | null;
  sender: string;
  subject: string;
  snippet: string;
  occurred_at: string;
  matched_confidence: number;
  classified_as: CommunicationClassification;
}

export interface CommunicationEventListResponse {
  items: CommunicationEventItem[];
  total: number;
  unmatched: number;
}

export interface LogRecruiterContactRequest {
  email: string;
  first_name?: string;
  last_name?: string;
  title?: string;
}

export interface LogRecruiterContactResponse {
  contact_id: string | null;
  matched_existing: boolean;
}
