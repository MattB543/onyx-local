"use client";

import { usePathname, useRouter } from "next/navigation";

import Tabs from "@/refresh-components/Tabs";

type CrmTab = "home" | "contacts" | "organizations";

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

  return "home";
}

export default function CrmNav({ rightContent }: CrmNavProps) {
  const pathname = usePathname();
  const router = useRouter();
  const activeTab = getCurrentTab(pathname);

  return (
    <Tabs
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

        router.push("/app/crm/organizations");
      }}
    >
      <Tabs.List
        variant="pill"
        rightContent={rightContent}
        className={`
          !bg-transparent
          [&_[role=tab][data-state=active]]:!bg-transparent
          [&_[role=tab][data-state=inactive]]:!bg-transparent
          [&_[role=tab][data-state=active]]:!text-text-05
        `}
      >
        <Tabs.Trigger value="home">Home</Tabs.Trigger>
        <Tabs.Trigger value="contacts">Contacts</Tabs.Trigger>
        <Tabs.Trigger value="organizations">Organizations</Tabs.Trigger>
      </Tabs.List>
    </Tabs>
  );
}
