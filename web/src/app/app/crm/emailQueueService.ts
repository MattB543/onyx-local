export interface PaginatedReturn<T> {
  items: T[];
  total_items: number;
}

export type CrmEmailQueueEventStatus =
  | "received"
  | "enqueued"
  | "consumed"
  | "dropped"
  | "failed";

export type CrmEmailQueueStatusFilter = "pending" | "failed" | "processed";

export interface CrmEmailQueueItem {
  id: string;
  status: CrmEmailQueueEventStatus;
  created_at: string;
  event_time: string | null;
  from_email: string | null;
  to_email: string | null;
  subject: string | null;
  run_status: string | null;
  error_message: string | null;
  document_id: string | null;
}

export interface CrmEmailQueueConfigStatus {
  // True when EMAIL_CRM_CUSTOM_JOB_ID is set AND is a valid UUID.
  configured: boolean;
  // True when EMAIL_CRM_CUSTOM_JOB_ID is set at all (even if invalid).
  env_value_set: boolean;
  job_exists: boolean;
  job_enabled: boolean;
  counts: Record<string, number>;
}

type QueryValue = string | number | boolean | null | undefined;

function withQueryParams(
  basePath: string,
  params: Record<string, QueryValue>
): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    search.append(key, String(value));
  });
  const queryString = search.toString();
  return queryString ? `${basePath}?${queryString}` : basePath;
}

async function getJson<T>(path: string, action: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${action} failed (Status: ${response.status})`);
  }
  return (await response.json()) as T;
}

export async function listCrmEmailQueue(args?: {
  status?: CrmEmailQueueStatusFilter;
  page_num?: number;
  page_size?: number;
}): Promise<PaginatedReturn<CrmEmailQueueItem>> {
  const path = withQueryParams("/api/user/crm/email-queue", {
    status: args?.status,
    page_num: args?.page_num ?? 0,
    page_size: args?.page_size ?? 25,
  });
  return getJson(path, "Fetch CRM email queue");
}

export async function getCrmEmailQueueConfigStatus(): Promise<CrmEmailQueueConfigStatus> {
  return getJson(
    "/api/user/crm/email-queue/config-status",
    "Fetch CRM email queue config status"
  );
}
