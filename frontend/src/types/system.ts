/** One dependency's connection state, mirrors the backend ServiceState. */
export interface ServiceState {
  key: string;
  label: string;
  /** "connected" | "pending" | "unavailable" | "not_configured" */
  status: string;
  detail: string;
  /** In-app route that lets the user act on a non-connected service, when one exists. */
  action_path: string;
  action_label: string;
}

/** The whole system status, mirrors the backend SystemStatusResponse. */
export interface SystemStatusResponse {
  services: ServiceState[];
  all_ok: boolean;
  attention: number;
}
