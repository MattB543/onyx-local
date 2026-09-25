import React from "react";
import "@testing-library/jest-dom";

import { render, screen } from "@tests/setup/test-utils";
import CrmInteractionsPage from "@/views/CrmInteractionsPage";

jest.mock("next/navigation", () => ({
  usePathname: () => "/app/crm/interactions",
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock("@/app/app/crm/crmService", () => ({
  exportCrmInteractions: jest.fn(),
  importCrmCsv: jest.fn(),
}));

jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: false }),
}));

jest.mock("@/lib/hooks/useInvalidateCrmCache", () => ({
  useInvalidateCrmCache: () => jest.fn(),
}));

jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: () => ({ data: [] }),
}));

jest.mock("@/lib/hooks/useCrmContactPrincipals", () => ({
  useCrmContactPrincipals: () => ({ principalOptions: [] }),
}));

jest.mock("@/lib/hooks/useCrmInteractions", () => ({
  useCrmInteractions: () => ({
    interactions: [],
    totalItems: 0,
    isLoading: false,
    error: undefined,
  }),
}));

test("the filter row sits in the filter-bar container", () => {
  render(<CrmInteractionsPage />);

  // The row's columns follow this container's width, not the viewport's, so
  // a 900px window keeps one row instead of stacking.
  const filterBar = screen
    .getByPlaceholderText("Filter by principal")
    .closest("[class*='@container/crmfilters']");
  expect(filterBar).not.toBeNull();
  expect(filterBar).toContainElement(screen.getByText("0 total"));
}, 60_000);
