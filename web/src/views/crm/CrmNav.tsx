"use client";

import "@/views/crm/crm.css";
import { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useLayoutEffect, useRef, useState } from "react";

import { Tabs } from "@opal/components";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";

type CrmTab =
  | "home"
  | "contacts"
  | "organizations"
  | "interactions"
  | "email-queue";

// The tabs (about 450px with Email Queue) and the widest actions ("New
// Organization" and its menu, about 205px) need about 655px on one line.
// Below this width the actions get their own row and the tabs scroll.
export const CRM_NAV_STACK_BELOW_PX = 680;

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

/**
 * True while the element is narrower than `widthPx`. It measures the element,
 * not the viewport, because the docked sidebar narrows the page. A width of 0
 * (not laid out yet) counts as wide.
 */
function useIsNarrowerThan(
  ref: React.RefObject<HTMLElement | null>,
  widthPx: number
): boolean {
  const [isNarrow, setIsNarrow] = useState(false);

  // A layout effect, so a phone gets the stacked layout before the first paint.
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;

    const update = (width: number) => {
      if (width > 0) setIsNarrow(width < widthPx);
    };
    update(element.getBoundingClientRect().width);

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) update(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, widthPx]);

  return isNarrow;
}

export default function CrmNav({ rightContent }: CrmNavProps) {
  const pathname = usePathname();
  const router = useRouter();
  const activeTab = getCurrentTab(pathname);
  // Email-queue endpoints require global MANAGE_CONNECTORS (admins hold it).
  const { isGlobalHolder: showEmailQueue } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );
  const navRef = useRef<HTMLDivElement>(null);
  const isStacked = useIsNarrowerThan(navRef, CRM_NAV_STACK_BELOW_PX);

  return (
    <div
      ref={navRef}
      // Marks the page for the scrollbar-gutter rule in crm.css.
      data-crm-nav=""
      className={`
        [&_.opal-tabs-list]:!bg-transparent
        [&_[role=tab][data-state=active]]:!bg-transparent
        [&_[role=tab][data-state=inactive]]:!bg-transparent
        [&_[role=tab][data-state=active]]:!text-text-05
      `}
    >
      {isStacked && rightContent && (
        <div className="flex justify-end pb-2">{rightContent}</div>
      )}

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
        {/* Narrow, the list's overflow-hidden would clip the last tabs, so
            they scroll behind arrow buttons instead. */}
        <Tabs.List
          rightChildren={isStacked ? undefined : rightContent}
          enableScrollArrows={isStacked}
        >
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
