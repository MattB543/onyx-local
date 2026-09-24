import React from "react";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";

import { render, screen } from "@tests/setup/test-utils";
import { createCrmOrganization } from "@/app/app/crm/crmService";
import CreateOrganizationModal from "@/views/crm/components/CreateOrganizationModal";

jest.mock("@/app/app/crm/crmService", () => ({
  createCrmOrganization: jest.fn(),
}));

jest.mock("@/lib/hooks/useInvalidateCrmCache", () => ({
  useInvalidateCrmCache: () => jest.fn(),
}));

test("shows the required-name message when the name is empty", async () => {
  const user = userEvent.setup({ delay: null });
  render(
    <CreateOrganizationModal
      open
      onOpenChange={jest.fn()}
      onSuccess={jest.fn()}
    />
  );

  // Whitespace only: the schema trims it, so it is still empty.
  await user.type(screen.getByPlaceholderText("Organization name *"), "   ");
  await user.click(screen.getByRole("button", { name: "Create Organization" }));

  expect(
    await screen.findByText("Organization name is required.")
  ).toBeInTheDocument();
  expect(createCrmOrganization).not.toHaveBeenCalled();
}, 60_000);
