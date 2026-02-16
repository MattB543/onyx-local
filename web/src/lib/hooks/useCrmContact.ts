"use client";

import useSWR from "swr";
import { CrmContact, getCrmContact } from "@/app/app/crm/crmService";

export function useCrmContact(contactId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<CrmContact>(
    contactId ? ["crm-contact", contactId] : null,
    () => getCrmContact(contactId as string),
    {
      revalidateOnFocus: false,
    }
  );

  return {
    contact: data ?? null,
    isLoading,
    error,
    refreshContact: mutate,
  };
}
