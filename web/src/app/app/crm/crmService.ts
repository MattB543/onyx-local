export interface PaginatedReturn<T> {
  items: T[];
  total_items: number;
}

export type CrmContactSource =
  | "manual"
  | "import"
  | "referral"
  | "inbound"
  | "other";
export type CrmContactStatus = "lead" | "active" | "inactive" | "archived";
export type CrmOrganizationType =
  | "customer"
  | "prospect"
  | "partner"
  | "vendor"
  | "other";
export type CrmInteractionType = "note" | "call" | "email" | "meeting" | "event";
export type CrmAttendeeRole = "organizer" | "attendee" | "observer";
export type CrmSearchEntityType = "contact" | "organization" | "interaction" | "tag";

export interface CrmTag {
  id: string;
  name: string;
  color: string | null;
  created_at: string;
}

export interface CrmContact {
  id: string;
  first_name: string;
  last_name: string | null;
  full_name: string;
  email: string | null;
  phone: string | null;
  title: string | null;
  organization_id: string | null;
  owner_id: string | null;
  source: CrmContactSource | null;
  status: CrmContactStatus;
  notes: string | null;
  linkedin_url: string | null;
  location: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  tags: CrmTag[];
}

export interface CrmOrganization {
  id: string;
  name: string;
  website: string | null;
  type: CrmOrganizationType | null;
  sector: string | null;
  location: string | null;
  size: string | null;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  tags: CrmTag[];
}

export interface CrmInteractionAttendee {
  id: number;
  user_id: string | null;
  contact_id: string | null;
  role: CrmAttendeeRole;
  created_at: string;
}

export interface CrmInteraction {
  id: string;
  contact_id: string | null;
  organization_id: string | null;
  logged_by: string | null;
  type: CrmInteractionType;
  title: string;
  summary: string | null;
  occurred_at: string | null;
  created_at: string;
  updated_at: string;
  attendees: CrmInteractionAttendee[];
}

export interface CrmSearchResultItem {
  entity_type: CrmSearchEntityType;
  entity_id: string;
  primary_text: string;
  secondary_text: string | null;
  rank: number;
  sort_at: string | null;
}

export interface CrmSettings {
  enabled: boolean;
  tier2_enabled: boolean;
  tier3_deals: boolean;
  tier3_custom_fields: boolean;
  updated_by: string | null;
  updated_at: string;
}

type QueryValue = string | number | boolean | null | undefined;

function handleRequestError(action: string, response: Response): never {
  throw new Error(`${action} failed (Status: ${response.status})`);
}

function withQueryParams(
  basePath: string,
  params: Record<string, QueryValue | QueryValue[]>
): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== "") {
          search.append(key, String(item));
        }
      });
    } else {
      search.append(key, String(value));
    }
  });
  const queryString = search.toString();
  return queryString ? `${basePath}?${queryString}` : basePath;
}

async function getJson<T>(path: string, action: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    handleRequestError(action, response);
  }
  return (await response.json()) as T;
}

async function postJson<T>(
  path: string,
  body: unknown,
  action: string,
  method: "POST" | "PATCH" | "DELETE" = "POST"
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    handleRequestError(action, response);
  }
  return (await response.json()) as T;
}

async function deleteJson<T>(path: string, action: string): Promise<T> {
  return postJson<T>(path, {}, action, "DELETE");
}

export async function getCrmSettings(): Promise<CrmSettings> {
  return getJson<CrmSettings>("/api/user/crm/settings", "Fetch CRM settings");
}

export async function patchCrmSettings(
  patch: Partial<
    Pick<
      CrmSettings,
      "enabled" | "tier2_enabled" | "tier3_deals" | "tier3_custom_fields"
    >
  >
): Promise<CrmSettings> {
  return postJson<CrmSettings>(
    "/api/user/crm/settings",
    patch,
    "Patch CRM settings",
    "PATCH"
  );
}

export async function searchCrmEntities(args: {
  q: string;
  entity_types?: CrmSearchEntityType[];
  page_num?: number;
  page_size?: number;
}): Promise<PaginatedReturn<CrmSearchResultItem>> {
  const path = withQueryParams("/api/user/crm/search", {
    q: args.q,
    entity_types: args.entity_types,
    page_num: args.page_num ?? 0,
    page_size: args.page_size ?? 25,
  });
  return getJson(path, "Search CRM entities");
}

export async function listCrmContacts(args?: {
  q?: string;
  status?: CrmContactStatus;
  organization_id?: string;
  tag_ids?: string[];
  page_num?: number;
  page_size?: number;
}): Promise<PaginatedReturn<CrmContact>> {
  const path = withQueryParams("/api/user/crm/contacts", {
    q: args?.q,
    status: args?.status,
    organization_id: args?.organization_id,
    tag_ids: args?.tag_ids,
    page_num: args?.page_num ?? 0,
    page_size: args?.page_size ?? 25,
  });
  return getJson(path, "Fetch CRM contacts");
}

export async function getCrmContact(contactId: string): Promise<CrmContact> {
  return getJson(`/api/user/crm/contacts/${contactId}`, "Fetch CRM contact");
}

export async function createCrmContact(
  body: Partial<CrmContact> & Pick<CrmContact, "first_name">
): Promise<CrmContact> {
  return postJson("/api/user/crm/contacts", body, "Create CRM contact");
}

export async function patchCrmContact(
  contactId: string,
  patch: Partial<CrmContact>
): Promise<CrmContact> {
  return postJson(
    `/api/user/crm/contacts/${contactId}`,
    patch,
    "Patch CRM contact",
    "PATCH"
  );
}

export async function listCrmOrganizations(args?: {
  q?: string;
  tag_ids?: string[];
  page_num?: number;
  page_size?: number;
}): Promise<PaginatedReturn<CrmOrganization>> {
  const path = withQueryParams("/api/user/crm/organizations", {
    q: args?.q,
    tag_ids: args?.tag_ids,
    page_num: args?.page_num ?? 0,
    page_size: args?.page_size ?? 25,
  });
  return getJson(path, "Fetch CRM organizations");
}

export async function getCrmOrganization(
  organizationId: string
): Promise<CrmOrganization> {
  return getJson(
    `/api/user/crm/organizations/${organizationId}`,
    "Fetch CRM organization"
  );
}

export async function createCrmOrganization(
  body: Partial<CrmOrganization> & Pick<CrmOrganization, "name">
): Promise<CrmOrganization> {
  return postJson(
    "/api/user/crm/organizations",
    body,
    "Create CRM organization"
  );
}

export async function patchCrmOrganization(
  organizationId: string,
  patch: Partial<CrmOrganization>
): Promise<CrmOrganization> {
  return postJson(
    `/api/user/crm/organizations/${organizationId}`,
    patch,
    "Patch CRM organization",
    "PATCH"
  );
}

export async function listCrmInteractions(args?: {
  contact_id?: string;
  organization_id?: string;
  page_num?: number;
  page_size?: number;
}): Promise<PaginatedReturn<CrmInteraction>> {
  const path = withQueryParams("/api/user/crm/interactions", {
    contact_id: args?.contact_id,
    organization_id: args?.organization_id,
    page_num: args?.page_num ?? 0,
    page_size: args?.page_size ?? 25,
  });
  return getJson(path, "Fetch CRM interactions");
}

export async function createCrmInteraction(
  body: Partial<CrmInteraction> &
    Pick<CrmInteraction, "title" | "type"> & {
      attendees?: {
        user_id?: string | null;
        contact_id?: string | null;
        role?: CrmAttendeeRole;
      }[];
    }
): Promise<CrmInteraction> {
  return postJson(
    "/api/user/crm/interactions",
    body,
    "Create CRM interaction"
  );
}

export async function listCrmTags(args?: {
  q?: string;
  page_num?: number;
  page_size?: number;
}): Promise<PaginatedReturn<CrmTag>> {
  const path = withQueryParams("/api/user/crm/tags", {
    q: args?.q,
    page_num: args?.page_num ?? 0,
    page_size: args?.page_size ?? 25,
  });
  return getJson(path, "Fetch CRM tags");
}

export async function createCrmTag(body: {
  name: string;
  color?: string | null;
}): Promise<CrmTag> {
  return postJson("/api/user/crm/tags", body, "Create CRM tag");
}

export async function addTagToContact(
  contactId: string,
  tagId: string
): Promise<CrmTag[]> {
  return postJson(
    `/api/user/crm/contacts/${contactId}/tags/${tagId}`,
    {},
    "Assign CRM tag to contact"
  );
}

export async function removeTagFromContact(
  contactId: string,
  tagId: string
): Promise<CrmTag[]> {
  return deleteJson(
    `/api/user/crm/contacts/${contactId}/tags/${tagId}`,
    "Unassign CRM tag from contact"
  );
}

export async function addTagToOrganization(
  organizationId: string,
  tagId: string
): Promise<CrmTag[]> {
  return postJson(
    `/api/user/crm/organizations/${organizationId}/tags/${tagId}`,
    {},
    "Assign CRM tag to organization"
  );
}

export async function removeTagFromOrganization(
  organizationId: string,
  tagId: string
): Promise<CrmTag[]> {
  return deleteJson(
    `/api/user/crm/organizations/${organizationId}/tags/${tagId}`,
    "Unassign CRM tag from organization"
  );
}
