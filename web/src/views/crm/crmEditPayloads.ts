import type {
  CrmContactPatchBody,
  CrmContactSource,
  CrmContactStage,
  CrmOrganization,
  CrmOrganizationType,
} from "@/app/app/crm/crmService";

/**
 * PATCH bodies for the contact / organization edit forms.
 *
 * The backend applies PATCHes with `exclude_unset=True`, so an omitted key
 * keeps the stored value. Optional text fields therefore send an explicit
 * `null` when emptied (`undefined` is dropped by JSON serialization and the
 * field could never be cleared).
 */
export function nullableText(value: string): string | null {
  return value.trim() || null;
}

export interface ContactEditValues {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  location: string;
  linkedin_url: string;
  status: CrmContactStage;
  category: string;
  party_affiliation: string;
  us_state: string;
  principal: string;
  /** Linked official's contact id; "" when the principal is free text. */
  principal_contact_id: string;
  owner_ids: string[];
  source: CrmContactSource | "";
  notes: string;
  organization_id: string;
  organization_name: string;
}

/**
 * `preservedOwnerIds` are owners the form can't show (hidden or unresolvable
 * users); they are kept so saving the form never drops them.
 */
export function buildContactPatchBody(
  values: ContactEditValues,
  preservedOwnerIds: string[]
): CrmContactPatchBody {
  return {
    first_name: nullableText(values.first_name),
    last_name: nullableText(values.last_name),
    email: nullableText(values.email),
    phone: nullableText(values.phone),
    title: nullableText(values.title),
    location: nullableText(values.location),
    linkedin_url: nullableText(values.linkedin_url),
    status: values.status,
    category: nullableText(values.category),
    party_affiliation: nullableText(values.party_affiliation),
    us_state: nullableText(values.us_state),
    principal: nullableText(values.principal),
    // An id, not text: "" means unlinked, so send null to drop a link.
    principal_contact_id: values.principal_contact_id || null,
    owner_ids: Array.from(new Set([...values.owner_ids, ...preservedOwnerIds])),
    // The source select has no "none" item, so "" only means "never set";
    // leave it out rather than sending null.
    source: values.source || undefined,
    notes: nullableText(values.notes),
    organization_id: values.organization_id || null,
  };
}

export interface OrganizationEditValues {
  name: string;
  website: string;
  type: CrmOrganizationType | "";
  sector: string;
  location: string;
  size: string;
  notes: string;
}

export function buildOrganizationPatchBody(
  values: OrganizationEditValues
): Partial<CrmOrganization> {
  return {
    // Required: the backend rejects an empty or null name.
    name: values.name.trim(),
    website: nullableText(values.website),
    // Like the contact source, the type select can't be emptied.
    type: values.type || undefined,
    sector: nullableText(values.sector),
    location: nullableText(values.location),
    size: nullableText(values.size),
    notes: nullableText(values.notes),
  };
}
