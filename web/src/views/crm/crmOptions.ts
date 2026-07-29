import * as Yup from "yup";

import {
  CrmContactSource,
  CrmOrganizationType,
} from "@/app/app/crm/crmService";

export const DEFAULT_CRM_STAGE_OPTIONS = [
  "lead",
  "active",
  "inactive",
  "archived",
];

export const DEFAULT_CRM_CATEGORY_SUGGESTIONS = [
  "Policy Maker",
  "Journalist",
  "Academic",
  "Allied Org",
  "Lab Member",
];

export const ORGANIZATION_TYPE_OPTIONS: CrmOrganizationType[] = [
  "customer",
  "prospect",
  "partner",
  "vendor",
  "other",
];

export const CONTACT_SOURCES: CrmContactSource[] = [
  "manual",
  "import",
  "referral",
  "inbound",
  "other",
];

export const contactValidationSchema = Yup.object().shape(
  {
    first_name: Yup.string()
      .trim()
      .when("last_name", {
        is: (last_name?: string) => !last_name || !last_name.trim(),
        then: (schema) =>
          schema.required("Enter a first name or a last name."),
        otherwise: (schema) => schema.optional(),
      }),
    last_name: Yup.string()
      .trim()
      .when("first_name", {
        is: (first_name?: string) => !first_name || !first_name.trim(),
        then: (schema) =>
          schema.required("Enter a first name or a last name."),
        otherwise: (schema) => schema.optional(),
      }),
    email: Yup.string().trim().email("Enter a valid email.").optional(),
  },
  [["first_name", "last_name"]] // declare the cyclic dependency
);

export type CrmSortValue =
  | "created_asc"
  | "created_desc"
  | "updated_asc"
  | "updated_desc";

export const CRM_SORT_OPTIONS: { value: CrmSortValue; label: string }[] = [
  { value: "created_asc", label: "Created asc" },
  { value: "created_desc", label: "Created desc" },
  { value: "updated_asc", label: "Updated asc" },
  { value: "updated_desc", label: "Updated desc" },
];

export const DEFAULT_CRM_SORT_VALUE: CrmSortValue = "updated_desc";

export function sortValueToParams(v: CrmSortValue): {
  sortBy: "created_at" | "updated_at";
  sortDir: "asc" | "desc";
} {
  const [field, dir] = v.split("_") as ["created" | "updated", "asc" | "desc"];
  return {
    sortBy: field === "created" ? "created_at" : "updated_at",
    sortDir: dir,
  };
}

export function formatCrmLabel(value: string): string {
  return value
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function optionalText(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}
