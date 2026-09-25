import React from "react";
import "@testing-library/jest-dom";

import { render, screen } from "@tests/setup/test-utils";
import InputMultiSelect from "@/refresh-components/inputs/InputMultiSelect";

const OPTIONS = [
  { value: "a", label: "Avery Tester" },
  { value: "e", label: "Emery Tester" },
];

test("shows the picked values as chips above the select by default", () => {
  // The modal attendee fields have always put the chips above the select.
  render(
    <InputMultiSelect
      value={["a", "e"]}
      onChange={jest.fn()}
      options={OPTIONS}
      placeholder="Select contact attendee(s)"
    />
  );

  const chip = screen.getByText("Avery Tester");
  const select = screen.getByPlaceholderText("Select contact attendee(s)");
  expect(screen.getByText("Emery Tester")).toBeInTheDocument();
  expect(
    chip.compareDocumentPosition(select) & Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Remove Avery Tester" })
  ).toBeInTheDocument();
});

test("leaves the chips to the caller when showChips is false", () => {
  // The filter bars render MultiSelectChips under all the filters instead.
  render(
    <InputMultiSelect
      value={["a"]}
      onChange={jest.fn()}
      options={OPTIONS}
      placeholder="Filter by tags"
      showChips={false}
    />
  );

  expect(screen.queryByText("Avery Tester")).not.toBeInTheDocument();
});
