"use client";

import Link from "next/link";

import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import { Text } from "@opal/components";
import { formatRelativeDate } from "@/views/crm/components/crmDateUtils";

interface OfficeActivitySummaryProps {
  principal: string;
}

/** When the office was last contacted and how often, with a link to its
 * interactions. */
export default function OfficeActivitySummary({
  principal,
}: OfficeActivitySummaryProps) {
  const { interactions, totalItems, isLoading } = useCrmInteractions({
    principal,
    pageNum: 0,
    pageSize: 1,
  });

  if (isLoading) {
    return null;
  }

  const latest = interactions[0];
  if (!latest) {
    return (
      <Text as="p" font="secondary-body" color="text-03">
        No interactions with this office yet.
      </Text>
    );
  }

  return (
    <Link
      href={`/app/crm/interactions?principal=${encodeURIComponent(principal)}`}
      className="self-start hover:underline"
    >
      <Text font="secondary-body" color="text-03">
        {`Last interaction with this office: ${formatRelativeDate(
          latest.occurred_at || latest.created_at
        )} · ${totalItems} ${
          totalItems === 1 ? "interaction" : "interactions"
        }`}
      </Text>
    </Link>
  );
}
