"use client";

import Link from "next/link";
import { ChangeEvent, useMemo, useState } from "react";

import { useCrmContactPrincipals } from "@/lib/hooks/useCrmContactPrincipals";
import { Button, InputTypeIn, Text } from "@opal/components";
import { SvgChevronRight } from "@opal/icons";
import Card from "@/refresh-components/cards/Card";
import { formatPrincipalOffice } from "@/views/crm/crmOptions";

const VISIBLE_OFFICE_COUNT = 10;

interface OfficeRowProps {
  /** Filters for the contacts list that the row opens. */
  query: Record<string, string>;
  label: string;
  count: string;
}

function OfficeRow({ query, label, count }: OfficeRowProps) {
  return (
    <Link
      href={{ pathname: "/app/crm/contacts", query }}
      className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-1 transition-colors hover:bg-background-tint-02"
    >
      <div className="min-w-0">
        <Text font="main-ui-action" color="text-04" maxLines={1}>
          {label}
        </Text>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Text font="secondary-body" color="text-03">
          {count}
        </Text>
        <SvgChevronRight size={16} className="stroke-text-03" />
      </div>
    </Link>
  );
}

interface OrganizationOfficesCardProps {
  organizationId: string;
  /** All of the organization's contacts, with or without a principal. */
  contactCount: number;
}

/** The organization's contacts grouped by principal, largest office first.
 * Renders nothing when no contact of the organization has a principal. */
export default function OrganizationOfficesCard({
  organizationId,
  contactCount,
}: OrganizationOfficesCardProps) {
  const { principals } = useCrmContactPrincipals(organizationId);
  const [filterText, setFilterText] = useState("");
  const [showAll, setShowAll] = useState(false);

  const offices = useMemo(
    () =>
      [...principals].sort(
        (a, b) =>
          b.contact_count - a.contact_count || a.name.localeCompare(b.name)
      ),
    [principals]
  );

  if (offices.length === 0) {
    return null;
  }

  const query = filterText.trim().toLowerCase();
  const matching = query
    ? offices.filter((office) => office.name.toLowerCase().includes(query))
    : offices;
  const visible =
    showAll || query ? matching : matching.slice(0, VISIBLE_OFFICE_COUNT);
  const hasMore = offices.length > VISIBLE_OFFICE_COUNT;
  const staffCount = offices.reduce(
    (sum, office) => sum + office.contact_count,
    0
  );
  const noPrincipalCount = contactCount - staffCount;

  return (
    <Card variant="secondary" className="gap-3 [&>div]:items-stretch">
      <Text as="p" font="main-ui-action" color="text-02">
        {`Offices (${offices.length})`}
      </Text>

      {hasMore && (
        <InputTypeIn
          value={filterText}
          onChange={(event: ChangeEvent<HTMLInputElement>) =>
            setFilterText(event.target.value)
          }
          placeholder="Filter offices"
          searchIcon
        />
      )}

      <div className="flex w-full flex-col gap-1">
        {visible.map((office) => (
          <OfficeRow
            key={office.name}
            query={{ organization_id: organizationId, principal: office.name }}
            label={formatPrincipalOffice(office.name)}
            count={`${office.contact_count} staff`}
          />
        ))}
        {query && matching.length === 0 && (
          <Text as="p" font="secondary-body" color="text-03">
            No office matches this filter.
          </Text>
        )}
        {!query && noPrincipalCount > 0 && (
          <OfficeRow
            query={{ organization_id: organizationId }}
            label="No principal"
            count={`${noPrincipalCount} ${
              noPrincipalCount === 1 ? "contact" : "contacts"
            }`}
          />
        )}
      </div>

      {hasMore && !query && (
        <div>
          <Button
            variant="action"
            prominence="tertiary"
            size="md"
            onClick={() => setShowAll((value) => !value)}
          >
            {showAll
              ? "Show fewer offices"
              : `Show all ${offices.length} offices`}
          </Button>
        </div>
      )}
    </Card>
  );
}
