"use client";

import { usePathname } from "next/navigation";
import Button from "@/refresh-components/buttons/Button";

export default function CrmNav() {
  const pathname = usePathname();
  const inOrganizations = pathname.startsWith("/app/crm/organizations");
  const inContacts = !inOrganizations;

  return (
    <div className="flex gap-2">
      <Button
        main
        primary
        href="/app/crm/contacts"
        transient={inContacts}
        size="md"
      >
        Contacts
      </Button>
      <Button
        main
        primary
        href="/app/crm/organizations"
        transient={inOrganizations}
        size="md"
      >
        Organizations
      </Button>
    </div>
  );
}
