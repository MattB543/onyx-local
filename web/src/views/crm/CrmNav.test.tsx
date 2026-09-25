import React from "react";
import "@testing-library/jest-dom";

import { render, screen } from "@tests/setup/test-utils";
import { Button } from "@opal/components";
import CrmNav, { CRM_NAV_STACK_BELOW_PX } from "@/views/crm/CrmNav";

jest.mock("next/navigation", () => ({
  usePathname: () => "/app/crm/contacts",
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: true }),
}));

// Reports a fixed width for every observed element, like a laid-out page.
function mockElementWidth(width: number) {
  global.ResizeObserver = class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) {
      this.callback(
        [{ target, contentRect: { width } } as ResizeObserverEntry],
        this as unknown as ResizeObserver
      );
    }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

function renderNav() {
  render(<CrmNav rightContent={<Button>New Contact</Button>} />);
}

test("keeps the actions in the tab row when the row has room", () => {
  mockElementWidth(CRM_NAV_STACK_BELOW_PX + 200);
  renderNav();

  const tabList = screen.getByRole("tablist");
  expect(tabList).toContainElement(
    screen.getByRole("button", { name: "New Contact" })
  );
  expect(screen.getByRole("tab", { name: "Email Queue" })).toBeInTheDocument();
});

test("moves the actions to their own row on a narrow page", () => {
  // About a 400px phone: the one-line row would clip the last tabs.
  mockElementWidth(353);
  renderNav();

  const tabList = screen.getByRole("tablist");
  expect(tabList).not.toContainElement(
    screen.getByRole("button", { name: "New Contact" })
  );
  // Every tab is still rendered, inside the scrollable list.
  expect(screen.getAllByRole("tab")).toHaveLength(5);
});
