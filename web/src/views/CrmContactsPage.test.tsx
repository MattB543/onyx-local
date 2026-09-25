import React from "react";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";

import { render, screen } from "@tests/setup/test-utils";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import CrmContactsPage from "@/views/CrmContactsPage";

jest.mock("next/navigation", () => ({
  usePathname: () => "/app/crm/contacts",
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock("@/app/app/crm/crmService", () => ({
  exportCrmContacts: jest.fn(),
  importCrmCsv: jest.fn(),
  // Never settles, so the tag list does not update after a test ends.
  listCrmTags: jest.fn(() => new Promise(() => {})),
}));

jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: false }),
}));

jest.mock("@/lib/hooks/useInvalidateCrmCache", () => ({
  useInvalidateCrmCache: () => jest.fn(),
}));

jest.mock("@/lib/hooks/useCrmSettings", () => ({
  useCrmSettings: () => ({ crmSettings: null }),
}));

jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: () => ({ data: [] }),
}));

jest.mock("@/lib/hooks/useCrmOrganization", () => ({
  useCrmOrganization: () => ({ organization: null, isLoading: false }),
}));

jest.mock("@/lib/hooks/useCrmOrganizations", () => ({
  useCrmOrganizations: () => ({
    organizations: [],
    error: undefined,
    isLoading: false,
  }),
}));

jest.mock("@/lib/hooks/useCrmContactPrincipals", () => ({
  useCrmContactPrincipals: () => ({ principalOptions: [] }),
}));

jest.mock("@/lib/hooks/useCrmContacts", () => ({
  useCrmContacts: jest.fn(() => ({
    contacts: [],
    totalItems: 0,
    isLoading: false,
    error: undefined,
    refreshContacts: jest.fn(),
  })),
}));

const mockUseCrmContacts = useCrmContacts as jest.Mock;

/** The search term of the latest contacts query. */
function lastQuery(): string | undefined {
  const calls = mockUseCrmContacts.mock.calls;
  return calls[calls.length - 1]?.[0].q;
}

test("the search box and the contacts query always hold the same term", async () => {
  const user = userEvent.setup({ delay: null });
  const { unmount } = render(<CrmContactsPage />);

  await user.type(screen.getByPlaceholderText("Search contacts"), "Casey");
  expect(screen.getByPlaceholderText("Search contacts")).toHaveValue("Casey");
  expect(lastQuery()).toBe("Casey");

  // Leaving the page and coming back starts over: an empty box and no
  // search in the query, never one without the other.
  unmount();
  render(<CrmContactsPage />);
  expect(screen.getByPlaceholderText("Search contacts")).toHaveValue("");
  expect(lastQuery()).toBeUndefined();
}, 60_000);

test("every filter row sits in one filter-bar container", () => {
  render(<CrmContactsPage />);

  // One container gives the rows one even gap. Split across the page body,
  // the body's larger section gap opened under the search row.
  const filterBar = screen
    .getByPlaceholderText("Search contacts")
    .closest("[class*='@container/crmfilters']");
  expect(filterBar).not.toBeNull();
  expect(filterBar).toContainElement(
    screen.getByPlaceholderText("Filter by tags")
  );
  expect(filterBar).toContainElement(screen.getByText("0 total"));
}, 60_000);
