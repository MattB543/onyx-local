"use client";

import { useMemo } from "react";
import useSWR from "swr";

import {
  CrmPrincipalSummary,
  listCrmContactPrincipals,
} from "@/app/app/crm/crmService";
import type { ComboBoxOption } from "@/refresh-components/inputs/InputComboBox";

/** Distinct contact principals; with organizationId, only that org's contacts. */
export function useCrmContactPrincipals(organizationId?: string) {
  const { data, error, isLoading } = useSWR<CrmPrincipalSummary[]>(
    ["crm-contact-principals", organizationId ?? ""],
    () => listCrmContactPrincipals(organizationId),
    { revalidateOnFocus: false }
  );

  const principalOptions = useMemo<ComboBoxOption[]>(
    () =>
      (data ?? []).map((p) => ({
        value: p.name,
        label: p.name,
        description: `${p.contact_count} ${
          p.contact_count === 1 ? "contact" : "contacts"
        }`,
      })),
    [data]
  );

  return {
    principals: data ?? [],
    principalOptions,
    isLoading,
    error,
  };
}
