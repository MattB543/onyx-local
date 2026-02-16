"use client";

import useSWR from "swr";
import {
  CrmOrganization,
  PaginatedReturn,
  listCrmOrganizations,
} from "@/app/app/crm/crmService";

interface UseCrmOrganizationsParams {
  q?: string;
  pageNum: number;
  pageSize: number;
}

export function useCrmOrganizations({
  q,
  pageNum,
  pageSize,
}: UseCrmOrganizationsParams) {
  const { data, error, isLoading, mutate } = useSWR<
    PaginatedReturn<CrmOrganization>
  >(["crm-organizations", q ?? "", pageNum, pageSize], () =>
    listCrmOrganizations({
      q: q || undefined,
      page_num: pageNum,
      page_size: pageSize,
    })
  );

  return {
    organizations: data?.items ?? [],
    totalItems: data?.total_items ?? 0,
    isLoading,
    error,
    refreshOrganizations: mutate,
  };
}
