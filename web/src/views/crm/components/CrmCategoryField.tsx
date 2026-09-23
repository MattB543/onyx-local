"use client";

import { useField } from "formik";
import { useRef } from "react";
import type React from "react";

import { InputSingleSelect, type SelectOption } from "@opal/components";

/**
 * FORK-LOCAL (onyx-local): Formik binding for the CRM contact "category"
 * field — an open-set combo box (suggested categories plus free text).
 *
 * Upstream's `InputComboBoxField` writes every keystroke into Formik, which
 * makes the typed text the select's `value`; pressing Enter on the matching
 * option (or the create row) then hits `InputSingleSelect`'s "re-pick the
 * selected option unselects it" branch and commits "". This wrapper keeps
 * the typed text as a local draft instead:
 *
 * - picking an option or the create row (click or Enter) commits it via
 *   `onValueChange` — re-picking the committed value still toggles it off;
 * - leaving the field (blur, Tab, clicking Save) commits the draft if it
 *   differs from the committed value, so typed free text is never lost and
 *   clearing the text clears the category;
 * - Escape and the chevron revert the visible text to the committed value,
 *   so they discard the draft too.
 *
 * Kept outside the upstream files so upstream syncs don't conflict.
 */
interface CrmCategoryFieldProps {
  name: string;
  options: SelectOption[];
  placeholder: string;
}

export default function CrmCategoryField({
  name,
  options,
  placeholder,
}: CrmCategoryFieldProps) {
  const [field, meta, helpers] = useField<string>(name);
  const committed = field.value ?? "";
  // Text typed since the last commit; null while nothing is pending.
  const draftRef = useRef<string | null>(null);

  const commit = (next: string) => {
    draftRef.current = null;
    helpers.setTouched(true, false);
    helpers.setValue(next);
  };

  const handleBlur = (event: React.FocusEvent<HTMLDivElement>) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;

    // Focus moving into our own dropdown (it is portaled, so it is not a DOM
    // descendant) is not "leaving": an option click commits on its own, and
    // committing the draft first would turn that click into a toggle-off.
    const next = event.relatedTarget;
    const listboxId = input.getAttribute("aria-controls");
    const listbox = listboxId ? document.getElementById(listboxId) : null;
    if (
      next instanceof Node &&
      (event.currentTarget.contains(next) || listbox?.contains(next))
    ) {
      return;
    }

    const draft = draftRef.current;
    if (draft === null) return;
    draftRef.current = null;

    const trimmed = draft.trim();
    const lowered = trimmed.toLowerCase();
    const matched = trimmed
      ? options.find(
          (option) =>
            option.value.toLowerCase() === lowered ||
            option.label.toLowerCase() === lowered
        )
      : undefined;
    const nextValue = matched?.value ?? trimmed;
    if (nextValue !== committed) commit(nextValue);
  };

  return (
    <div
      role="presentation"
      className="w-full"
      onBlur={handleBlur}
      onKeyDownCapture={(event) => {
        if (event.key === "Escape") draftRef.current = null;
      }}
      onClickCapture={(event) => {
        const target = event.target;
        const button =
          target instanceof Element ? target.closest("button") : null;
        if (button && event.currentTarget.contains(button)) {
          draftRef.current = null;
        }
      }}
    >
      <InputSingleSelect
        name={name}
        mode="open"
        options={options}
        placeholder={placeholder}
        value={committed}
        // Fires per keystroke (and once, synthetically, before
        // onValueChange on a pick): track the draft only, never Formik.
        onChange={(event) => {
          draftRef.current = event.target.value;
        }}
        onValueChange={commit}
        isError={meta.touched && meta.error ? true : undefined}
      />
    </div>
  );
}
