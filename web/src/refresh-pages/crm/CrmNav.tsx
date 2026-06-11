"use client";

import { Route } from "next";
import { usePathname, useRouter } from "next/navigation";

import { Tabs } from "@opal/components";
import { useUser } from "@/providers/UserProvider";

type CrmTab =
  | "home"
  | "contacts"
  | "organizations"
  | "interactions"
  | "email-queue";

interface CrmNavProps {
  rightContent?: React.ReactNode;
}

function getCurrentTab(pathname: string): CrmTab {
  if (pathname.startsWith("/app/crm/organizations")) {
    return "organizations";
  }

  if (pathname.startsWith("/app/crm/contacts")) {
    return "contacts";
  }

  if (pathname.startsWith("/app/crm/interactions")) {
    return "interactions";
  }

  if (pathname.startsWith("/app/crm/email-queue")) {
    return "email-queue";
  }

  return "home";
}

export default function CrmNav({ rightContent }: CrmNavProps) {
  const pathname = usePathname();
  const router = useRouter();
  const activeTab = getCurrentTab(pathname);
  const { isAdmin, isCurator } = useUser();
  const showEmailQueue = isAdmin || isCurator;

  return (
    <div
      className={`
        [&_.opal-tabs-list]:!bg-transparent
        [&_[role=tab][data-state=active]]:!bg-transparent
        [&_[role=tab][data-state=inactive]]:!bg-transparent
        [&_[role=tab][data-state=active]]:!text-text-05
      `}
    >
      <Tabs
        variant="pill"
        value={activeTab}
        onValueChange={(value) => {
          const nextTab = value as CrmTab;

          if (nextTab === "home") {
            router.push("/app/crm");
            return;
          }

          if (nextTab === "contacts") {
            router.push("/app/crm/contacts");
            return;
          }

          if (nextTab === "interactions") {
            router.push("/app/crm/interactions" as Route);
            return;
          }

          if (nextTab === "email-queue") {
            router.push("/app/crm/email-queue" as Route);
            return;
          }

          router.push("/app/crm/organizations");
        }}
      >
        <Tabs.List rightChildren={rightContent}>
          <Tabs.Trigger value="home">Home</Tabs.Trigger>
          <Tabs.Trigger value="contacts">Contacts</Tabs.Trigger>
          <Tabs.Trigger value="organizations">Organizations</Tabs.Trigger>
          <Tabs.Trigger value="interactions">Interactions</Tabs.Trigger>
          {showEmailQueue && (
            <Tabs.Trigger value="email-queue">Email Queue</Tabs.Trigger>
          )}
        </Tabs.List>
      </Tabs>
    </div>
  );
}
