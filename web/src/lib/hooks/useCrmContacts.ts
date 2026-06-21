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
  ownerIds?: string[];
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

export function useCrmContacts({
  q,
  status,
  category,
  organizationId,
  ownerIds,
  tagIds,
  createdAfter,
  createdBefore,
  updatedAfter,
  updatedBefore,
  sortBy,
  sortDir,
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
      ownerIds?.join(",") ?? "",
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
      listCrmContacts({
        q: q || undefined,
        status,
        category,
        organization_id: organizationId,
        owner_ids: ownerIds?.length ? ownerIds : undefined,
        tag_ids: tagIds?.length ? tagIds : undefined,
        created_after: createdAfter,
        created_before: createdBefore,
        updated_after: updatedAfter,
        updated_before: updatedBefore,
        sort_by: sortBy,
        sort_dir: sortDir,
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
