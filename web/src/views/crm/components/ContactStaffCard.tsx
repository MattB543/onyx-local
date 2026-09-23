"use client";

import Link from "next/link";

import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { Text } from "@opal/components";
import Card from "@/refresh-components/cards/Card";

const STAFF_PAGE_SIZE = 10;

interface ContactStaffCardProps {
  contactId: string;
  contactName: string;
}

/** The staffers whose principal links to this contact. Renders nothing when
 * no staffer links to it. */
export default function ContactStaffCard({
  contactId,
  contactName,
}: ContactStaffCardProps) {
  const { contacts: staff, totalItems } = useCrmContacts({
    principalContactId: contactId,
    pageNum: 0,
    pageSize: STAFF_PAGE_SIZE,
  });

  if (totalItems === 0) {
    return null;
  }

  return (
    <Card variant="secondary" className="gap-3 [&>div]:items-stretch">
      <Text as="p" font="main-ui-action" color="text-02">
        {`Staff (${totalItems})`}
      </Text>
      <div className="flex w-full flex-col gap-1">
        {staff.map((staffer) => (
          <Link
            key={staffer.id}
            href={`/app/crm/contacts/${staffer.id}`}
            className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-1 transition-colors hover:bg-background-tint-02"
          >
            <div className="min-w-0">
              <Text font="main-ui-action" color="text-04" maxLines={1}>
                {staffer.full_name || staffer.email || "Contact"}
              </Text>
            </div>
            <div className="min-w-0">
              <Text font="secondary-body" color="text-03" maxLines={1}>
                {staffer.title || "-"}
              </Text>
            </div>
          </Link>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        {totalItems > staff.length && (
          <Link
            href={`/app/crm/contacts?principal_contact_id=${contactId}`}
            className="hover:underline"
          >
            <Text font="secondary-body" color="text-04">
              {`View all ${totalItems} staff`}
            </Text>
          </Link>
        )}
        <Link
          href={`/app/crm/interactions?principal=${encodeURIComponent(
            contactName
          )}`}
          className="hover:underline"
        >
          <Text font="secondary-body" color="text-04">
            Office activity
          </Text>
        </Link>
      </div>
    </Card>
  );
}
