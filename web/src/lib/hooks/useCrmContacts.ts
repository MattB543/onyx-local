"use client";

import useSWR from "swr";
import {
  CrmContact,
  CrmContactStatus,
  PaginatedReturn,
  listCrmContacts,
} from "@/app/app/crm/crmService";

interface UseCrmContactsParams {
  q?: string;
  status?: CrmContactStatus;
  organizationId?: string;
  pageNum: number;
  pageSize: number;
}

export function useCrmContacts({
  q,
  status,
  organizationId,
  pageNum,
  pageSize,
}: UseCrmContactsParams) {
  const { data, error, isLoading, mutate } = useSWR<PaginatedReturn<CrmContact>>(
    ["crm-contacts", q ?? "", status ?? "", organizationId ?? "", pageNum, pageSize],
    () =>
      listCrmContacts({
        q: q || undefined,
        status,
        organization_id: organizationId,
        page_num: pageNum,
        page_size: pageSize,
      }),
    {
      revalidateOnFocus: false,
      dedupingInterval: 15000,
    }
  );

  return {
    contacts: data?.items ?? [],
    totalItems: data?.total_items ?? 0,
    isLoading,
    error,
    refreshContacts: mutate,
  };
}
