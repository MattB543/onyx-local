"use client";

import useSWR from "swr";
import {
  CrmOrganization,
  CrmOrganizationType,
  PaginatedReturn,
  listCrmOrganizations,
} from "@/app/app/crm/crmService";

interface UseCrmOrganizationsParams {
  q?: string;
  type?: CrmOrganizationType;
  sortBy?: string;
  pageNum: number;
  pageSize: number;
}

export function useCrmOrganizations({
  q,
  type,
  sortBy,
  pageNum,
  pageSize,
}: UseCrmOrganizationsParams) {
  const { data, error, isLoading, mutate } = useSWR<
    PaginatedReturn<CrmOrganization>
  >(
    ["crm-organizations", q ?? "", type ?? "", sortBy ?? "", pageNum, pageSize],
    () =>
      listCrmOrganizations({
        q: q || undefined,
        type: type || undefined,
        sort_by: sortBy,
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
