/** A harness-detected workflow/system anomaly (admin/health view).
 *  Corresponds to the backend `SystemIssueResponse` schema. */
export interface SystemIssue {
  id: string;
  user_id: string | null;
  category: string;
  severity: string;
  signals: Record<string, unknown>;
  diagnosis: string;
  status: string;
  detected_at: string;
  created_at: string;
}
