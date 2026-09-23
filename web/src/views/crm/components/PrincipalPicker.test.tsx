import React, { useState } from "react";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";

import { cleanup, render, screen } from "@tests/setup/test-utils";
import PrincipalPicker from "@/views/crm/components/PrincipalPicker";

// jsdom has no scrollIntoView; the dropdown calls it for the highlighted row.
Element.prototype.scrollIntoView = jest.fn();

jest.mock("@/lib/hooks/useCrmContactPrincipals", () => ({
  useCrmContactPrincipals: () => ({
    principals: [],
    principalOptions: [
      {
        value: "Sen. Jane Smith",
        label: "Sen. Jane Smith",
        description: "3 contacts",
      },
    ],
    isLoading: false,
    error: undefined,
  }),
}));

jest.mock("@/lib/hooks/useCrmContacts", () => ({
  useCrmContacts: () => ({
    contacts: [
      {
        id: "c-jane",
        full_name: "Jane Smith",
        title: "Senator",
        organization_name: "US Senate",
      },
      {
        id: "c-self",
        full_name: "Self Person",
        title: null,
        organization_name: null,
      },
    ],
  }),
}));

interface HarnessProps {
  initialPrincipal?: string;
  initialContactId?: string | null;
  onChangeSpy: jest.Mock;
}

function Harness({
  initialPrincipal = "",
  initialContactId = null,
  onChangeSpy,
}: HarnessProps) {
  const [state, setState] = useState({
    principal: initialPrincipal,
    contactId: initialContactId,
  });
  return (
    <>
      <PrincipalPicker
        principal={state.principal}
        principalContactId={state.contactId}
        onChange={(principal, contactId) => {
          onChangeSpy(principal, contactId);
          setState({ principal, contactId });
        }}
        excludeContactId="c-self"
        placeholder="Principal"
      />
      <output data-testid="principal">{state.principal}</output>
      <output data-testid="link">{state.contactId ?? ""}</output>
      <button type="button">Elsewhere</button>
    </>
  );
}

function renderPicker(props: Omit<HarnessProps, "onChangeSpy"> = {}) {
  const onChangeSpy = jest.fn();
  render(<Harness {...props} onChangeSpy={onChangeSpy} />);
  return {
    user: userEvent.setup({ delay: null }),
    input: screen.getByPlaceholderText("Principal"),
    principal: () => screen.getByTestId("principal").textContent,
    link: () => screen.getByTestId("link").textContent,
    onChangeSpy,
  };
}

describe("PrincipalPicker", () => {
  // Pay the cold start (providers, opal, jsdom) outside the per-test budget.
  beforeAll(() => {
    renderPicker();
    cleanup();
  }, 120_000);

  test("typing free text then leaving commits it unlinked", async () => {
    const { user, input, principal, link, onChangeSpy } = renderPicker();

    await user.click(input);
    await user.type(input, "Rep. Bob Lee");
    // Keystrokes stay a draft until the field is left.
    expect(onChangeSpy).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Elsewhere" }));

    expect(onChangeSpy).toHaveBeenLastCalledWith("Rep. Bob Lee", null);
    expect(principal()).toBe("Rep. Bob Lee");
    expect(link()).toBe("");
  });

  test("picking a contact links it and uses its name", async () => {
    const { user, input, principal, link } = renderPicker();

    await user.click(input);
    await user.type(input, "Jane");
    await user.click(
      await screen.findByRole("option", { name: /^Jane Smith/ })
    );

    expect(principal()).toBe("Jane Smith");
    expect(link()).toBe("c-jane");
    expect(
      screen.getByText("Linked to the official's contact record.")
    ).toBeInTheDocument();
  });

  test("never offers the contact being edited", async () => {
    const { user, input } = renderPicker();

    await user.click(input);
    await user.type(input, "Self");

    expect(
      screen.queryByRole("option", { name: /Self Person/ })
    ).not.toBeInTheDocument();
  });

  test("Escape discards the draft", async () => {
    const { user, input, principal, onChangeSpy } = renderPicker({
      initialPrincipal: "Sen. Jane Smith",
    });

    await user.click(input);
    await user.clear(input);
    await user.type(input, "Someone Else{Escape}");
    await user.click(screen.getByRole("button", { name: "Elsewhere" }));

    expect(onChangeSpy).not.toHaveBeenCalled();
    expect(principal()).toBe("Sen. Jane Smith");
  });

  test("leaving a linked principal's text unchanged keeps the link", async () => {
    const { user, input, link, onChangeSpy } = renderPicker({
      initialPrincipal: "Jane Smith",
      initialContactId: "c-jane",
    });

    await user.click(input);
    await user.clear(input);
    await user.type(input, "jane smith");
    await user.click(screen.getByRole("button", { name: "Elsewhere" }));

    expect(onChangeSpy).not.toHaveBeenCalled();
    expect(link()).toBe("c-jane");
  });

  test("emptying the field and leaving clears the principal and link", async () => {
    const { user, input, principal, link, onChangeSpy } = renderPicker({
      initialPrincipal: "Jane Smith",
      initialContactId: "c-jane",
    });

    await user.click(input);
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Elsewhere" }));

    expect(onChangeSpy).toHaveBeenLastCalledWith("", null);
    expect(principal()).toBe("");
    expect(link()).toBe("");
  });
});
