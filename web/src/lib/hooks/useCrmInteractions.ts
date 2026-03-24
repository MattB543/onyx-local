"use client";

import useSWR from "swr";
import {
  CrmInteraction,
  CrmInteractionType,
  PaginatedReturn,
  listCrmInteractions,
} from "@/app/app/crm/crmService";

interface UseCrmInteractionsParams {
  contactId?: string;
  organizationId?: string;
  interactionType?: CrmInteractionType;
  pageNum: number;
  pageSize: number;
}

export function useCrmInteractions({
  contactId,
  organizationId,
  interactionType,
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
      interactionType ?? "",
      pageNum,
      pageSize,
    ],
    () =>
      listCrmInteractions({
        contact_id: contactId,
        organization_id: organizationId,
        interaction_type: interactionType,
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
