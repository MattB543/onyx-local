"use client";

import useSWR from "swr";

import {
  CrmContact,
  CrmContactStage,
  PaginatedReturn,
  listCrmContacts,
} from "@/app/app/crm/crmService";

interface UseCrmContactsParams {
  q?: string;
  status?: CrmContactStage;
  category?: string;
  organizationId?: string;
  sortBy?: string;
  pageNum: number;
  pageSize: number;
}

export function useCrmContacts({
  q,
  status,
  category,
  organizationId,
  sortBy,
  pageNum,
  pageSize,
}: UseCrmContactsParams) {
  const { data, error, isLoading, mutate } = useSWR<
    PaginatedReturn<CrmContact>
  >(
    [
      "crm-contacts",
      q ?? "",
      status ?? "",
      category ?? "",
      organizationId ?? "",
      sortBy ?? "",
      pageNum,
      pageSize,
    ],
    () =>
      listCrmContacts({
        q: q || undefined,
        status,
        category,
        organization_id: organizationId,
        sort_by: sortBy,
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
