import * as Yup from "yup";

import { CrmContactSource } from "@/app/app/crm/crmService";

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

export const CONTACT_SOURCES: CrmContactSource[] = [
  "manual",
  "import",
  "referral",
  "inbound",
  "other",
];

export const contactValidationSchema = Yup.object().shape({
  first_name: Yup.string().trim().required("First name is required."),
  email: Yup.string().trim().email("Enter a valid email.").optional(),
});

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
