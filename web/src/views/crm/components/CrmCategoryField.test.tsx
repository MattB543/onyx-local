import React from "react";
import { Form, Formik, type FormikProps } from "formik";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";

import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import CrmCategoryField from "@/views/crm/components/CrmCategoryField";

// jsdom has no scrollIntoView; the dropdown calls it for the highlighted row.
Element.prototype.scrollIntoView = jest.fn();


const OPTIONS = ["Policy Maker", "Journalist", "Academic"].map((category) => ({
  value: category,
  label: category,
}));

function renderField(initialCategory = "") {
  const onSubmit = jest.fn();
  const formik = React.createRef<FormikProps<{ category: string }>>();
  render(
    <Formik
      innerRef={formik}
      initialValues={{ category: initialCategory }}
      onSubmit={(values) => onSubmit(values.category)}
    >
      {({ values }) => (
        <Form>
          <CrmCategoryField
            name="category"
            options={OPTIONS}
            placeholder="Category"
          />
          <output data-testid="committed">{values.category}</output>
          <button type="submit">Save</button>
        </Form>
      )}
    </Formik>
  );
  return {
    user: userEvent.setup({ delay: null }),
    input: screen.getByPlaceholderText("Category"),
    committed: () => screen.getByTestId("committed").textContent,
    onSubmit,
    formik,
  };
}

describe("CrmCategoryField", () => {
  // The first render pays a multi-second cold start (providers, opal, jsdom);
  // on a loaded machine that alone can blow a test's default 5s budget, so
  // pay it here instead.
  beforeAll(() => {
    renderField();
    cleanup();
  }, 120_000);

  test("typing an existing option then Enter commits it", async () => {
    const { user, input, committed, onSubmit } = renderField();

    await user.click(input);
    await user.type(input, "Journalist{Enter}");

    expect(committed()).toBe("Journalist");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("Journalist"));
  });

  test("typing a custom value then Enter commits it", async () => {
    const { user, input, committed } = renderField();

    await user.click(input);
    await user.type(input, "Custom Category{Enter}");

    expect(committed()).toBe("Custom Category");
    expect(input).toHaveValue("Custom Category");
  });

  test("typing a custom value then tabbing away commits it", async () => {
    const { user, input, committed } = renderField();

    await user.click(input);
    await user.type(input, "Custom Category");
    // Keystrokes stay a draft until the field is left.
    expect(committed()).toBe("");
    await user.tab();

    expect(committed()).toBe("Custom Category");
    expect(input).toHaveValue("Custom Category");
  });

  test("leaving the field maps typed text onto a matching option", async () => {
    const { user, input, committed } = renderField();

    await user.click(input);
    await user.type(input, "  journalist ");
    await user.tab();

    expect(committed()).toBe("Journalist");
  });

  test("typing a custom value then clicking Save submits it", async () => {
    const { user, input, onSubmit } = renderField("Journalist");

    await user.click(input);
    await user.clear(input);
    await user.type(input, "Custom Category");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith("Custom Category")
    );
  });

  test("clicking an option commits it", async () => {
    const { user, input, committed } = renderField();

    await user.click(input);
    await user.click(screen.getByRole("option", { name: "Academic" }));

    expect(committed()).toBe("Academic");
    expect(input).toHaveValue("Academic");
  });

  test("clicking the option matching the typed text commits it", async () => {
    const { user, input, committed } = renderField();

    await user.click(input);
    await user.type(input, "Journalist");
    await user.click(screen.getByRole("option", { name: "Journalist" }));

    expect(committed()).toBe("Journalist");
  });

  test("clearing the text then leaving the field clears the category", async () => {
    const { user, input, committed } = renderField("Journalist");

    await user.click(input);
    await user.clear(input);
    await user.tab();

    expect(committed()).toBe("");
  });

  test("re-picking the committed option clears it", async () => {
    const { user, input, committed } = renderField("Journalist");

    await user.click(input);
    await user.click(screen.getByRole("option", { name: "Journalist" }));

    expect(committed()).toBe("");
  });

  test("an external value change discards a pending draft", async () => {
    const { user, input, committed, formik } = renderField();

    await user.click(input);
    await user.type(input, "Draft");
    // e.g. the contact refetches while the field still has focus.
    await act(async () => {
      await formik.current?.setFieldValue("category", "Custom External");
    });
    await user.tab();

    expect(committed()).toBe("Custom External");
    // The select remounts to resync its text, so query the input afresh.
    expect(screen.getByPlaceholderText("Category")).toHaveValue(
      "Custom External"
    );
  });

  test("a form reset discards a pending draft", async () => {
    const { user, input, committed, formik } = renderField("Academic");

    await user.click(input);
    await user.clear(input);
    await user.type(input, "Draft");
    await act(async () => {
      formik.current?.resetForm({ values: { category: "Journalist" } });
    });
    await user.tab();

    expect(committed()).toBe("Journalist");
  });

  test("Escape discards the draft", async () => {
    const { user, input, committed } = renderField("Journalist");

    await user.click(input);
    await user.clear(input);
    await user.type(input, "Something Else{Escape}");
    await user.tab();

    expect(committed()).toBe("Journalist");
    expect(input).toHaveValue("Journalist");
  });
});
