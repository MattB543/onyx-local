"use client";

import useSWR from "swr";
import { CrmSettings, getCrmSettings } from "@/app/app/crm/crmService";

export function useCrmSettings() {
  const { data, error, isLoading, mutate } = useSWR<CrmSettings>(
    "crm-settings",
    () => getCrmSettings(),
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    }
  );

  return {
    crmSettings: data ?? null,
    isLoading,
    error,
    refreshCrmSettings: mutate,
  };
}
