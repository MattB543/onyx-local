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
  includeContactInteractions?: boolean;
  principal?: string;
  interactionType?: CrmInteractionType;
  loggedBy?: string;
  pageNum: number;
  pageSize: number;
}

export function useCrmInteractions({
  contactId,
  organizationId,
  includeContactInteractions,
  principal,
  interactionType,
  loggedBy,
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
      includeContactInteractions ?? false,
      principal ?? "",
      interactionType ?? "",
      loggedBy ?? "",
      pageNum,
      pageSize,
    ],
    () =>
      listCrmInteractions({
        contact_id: contactId,
        organization_id: organizationId,
        include_contact_interactions: includeContactInteractions,
        principal: principal || undefined,
        interaction_type: interactionType,
        logged_by: loggedBy || undefined,
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
