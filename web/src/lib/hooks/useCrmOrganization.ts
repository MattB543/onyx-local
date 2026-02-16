"use client";

import useSWR from "swr";
import {
  CrmOrganization,
  getCrmOrganization,
} from "@/app/app/crm/crmService";

export function useCrmOrganization(organizationId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<CrmOrganization>(
    organizationId ? ["crm-organization", organizationId] : null,
    () => getCrmOrganization(organizationId as string),
    {
      revalidateOnFocus: false,
    }
  );

  return {
    organization: data ?? null,
    isLoading,
    error,
    refreshOrganization: mutate,
  };
}
