"use client";

import useSWR from "swr";
import {
  CrmInteraction,
  PaginatedReturn,
  listCrmInteractions,
} from "@/app/app/crm/crmService";

interface UseCrmInteractionsParams {
  contactId?: string;
  organizationId?: string;
  pageNum: number;
  pageSize: number;
}

export function useCrmInteractions({
  contactId,
  organizationId,
  pageNum,
  pageSize,
}: UseCrmInteractionsParams) {
  const { data, error, isLoading, mutate } = useSWR<
    PaginatedReturn<CrmInteraction>
  >(
    [
      "crm-interactions",
      contactId ?? "",
      organizationId ?? "",
      pageNum,
      pageSize,
    ],
    () =>
      listCrmInteractions({
        contact_id: contactId,
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
    interactions: data?.items ?? [],
    totalItems: data?.total_items ?? 0,
    isLoading,
    error,
    refreshInteractions: mutate,
  };
}
