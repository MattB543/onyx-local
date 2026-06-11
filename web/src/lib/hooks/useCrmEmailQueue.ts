"use client";

import useSWR from "swr";
import {
  CrmEmailQueueConfigStatus,
  CrmEmailQueueItem,
  CrmEmailQueueStatusFilter,
  PaginatedReturn,
  getCrmEmailQueueConfigStatus,
  listCrmEmailQueue,
} from "@/app/app/crm/emailQueueService";

interface UseCrmEmailQueueParams {
  status?: CrmEmailQueueStatusFilter;
  pageNum: number;
  pageSize: number;
}

export function useCrmEmailQueue({
  status,
  pageNum,
  pageSize,
}: UseCrmEmailQueueParams) {
  const { data, error, isLoading, mutate } = useSWR<
    PaginatedReturn<CrmEmailQueueItem>
  >(
    ["crm-email-queue", status ?? "", pageNum, pageSize],
    () =>
      listCrmEmailQueue({
        status,
        page_num: pageNum,
        page_size: pageSize,
      }),
    {
      revalidateOnFocus: false,
      dedupingInterval: 15000,
    }
  );

  return {
    events: data?.items ?? [],
    totalItems: data?.total_items ?? 0,
    isLoading,
    error,
    refreshEmailQueue: mutate,
  };
}

export function useCrmEmailQueueConfigStatus() {
  const { data, error, isLoading } = useSWR<CrmEmailQueueConfigStatus>(
    "crm-email-queue-config-status",
    () => getCrmEmailQueueConfigStatus(),
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    }
  );

  return {
    configStatus: data,
    isLoading,
    error,
  };
}
