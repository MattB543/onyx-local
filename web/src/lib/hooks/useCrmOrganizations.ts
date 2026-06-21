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
  ownerId?: string;
  tagIds?: string[];
  createdAfter?: string;
  createdBefore?: string;
  updatedAfter?: string;
  updatedBefore?: string;
  sortBy?: "created_at" | "updated_at";
  sortDir?: "asc" | "desc";
  pageNum: number;
  pageSize: number;
}

export function useCrmOrganizations({
  q,
  type,
  ownerId,
  tagIds,
  createdAfter,
  createdBefore,
  updatedAfter,
  updatedBefore,
  sortBy,
  sortDir,
  pageNum,
  pageSize,
}: UseCrmOrganizationsParams) {
  const { data, error, isLoading, mutate } = useSWR<
    PaginatedReturn<CrmOrganization>
  >(
    [
      "crm-organizations",
      q ?? "",
      type ?? "",
      ownerId ?? "",
      tagIds?.join(",") ?? "",
      createdAfter ?? "",
      createdBefore ?? "",
      updatedAfter ?? "",
      updatedBefore ?? "",
      sortBy ?? "",
      sortDir ?? "",
      pageNum,
      pageSize,
    ],
    () =>
      listCrmOrganizations({
        q: q || undefined,
        type: type || undefined,
        owner_id: ownerId || undefined,
        tag_ids: tagIds?.length ? tagIds : undefined,
        created_after: createdAfter,
        created_before: createdBefore,
        updated_after: updatedAfter,
        updated_before: updatedBefore,
        sort_by: sortBy,
        sort_dir: sortDir,
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
