"use client";

import { useCallback } from "react";
import { useSWRConfig } from "swr";

const CRM_CACHE_KEYS = new Set([
  "crm-contact",
  "crm-contacts",
  "crm-organization",
  "crm-organizations",
  "crm-interactions",
]);

export function useInvalidateCrmCache() {
  const { mutate } = useSWRConfig();

  return useCallback(async () => {
    await mutate(
      (key: unknown) =>
        Array.isArray(key) &&
        typeof key[0] === "string" &&
        CRM_CACHE_KEYS.has(key[0]),
      undefined,
      { revalidate: true }
    );
  }, [mutate]);
}
