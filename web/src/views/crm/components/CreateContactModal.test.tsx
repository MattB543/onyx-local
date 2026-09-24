import React from "react";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";

import { render, screen } from "@tests/setup/test-utils";
import { createCrmContact } from "@/app/app/crm/crmService";
import CreateContactModal from "@/views/crm/components/CreateContactModal";

jest.mock("@/app/app/crm/crmService", () => ({
  createCrmContact: jest.fn(),
  uploadContactProfilePicture: jest.fn(),
}));

jest.mock("@/lib/hooks/useInvalidateCrmCache", () => ({
  useInvalidateCrmCache: () => jest.fn(),
}));

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: null }),
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

jest.mock("@/lib/hooks/useCrmContacts", () => ({
  useCrmContacts: () => ({ contacts: [] }),
}));

jest.mock("@/lib/hooks/useCrmContactPrincipals", () => ({
  useCrmContactPrincipals: () => ({ principalOptions: [] }),
}));

test("shows the name and email messages, the shared name rule once", async () => {
  const user = userEvent.setup({ delay: null });
  render(
    <CreateContactModal open onOpenChange={jest.fn()} onSuccess={jest.fn()} />
  );

  await user.type(screen.getByPlaceholderText("Email"), "not-an-email");
  await user.click(screen.getByRole("button", { name: "Create Contact" }));

  expect(await screen.findByText("Enter a valid email.")).toBeInTheDocument();
  expect(
    screen.getAllByText("Enter a first name or a last name.")
  ).toHaveLength(1);
  expect(createCrmContact).not.toHaveBeenCalled();
}, 60_000);
