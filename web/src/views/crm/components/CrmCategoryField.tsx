"use client";

import { useField, useFormikContext } from "formik";
import { useEffect, useRef, useState } from "react";
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
 *   so they discard the draft too;
 * - an external change (form re-initialization, programmatic setValue)
 *   discards a pending draft and resyncs the visible text, so a stale draft
 *   can never overwrite a newer value on the next blur.
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
  const { initialValues } = useFormikContext();
  const committed = field.value ?? "";
  // Text typed since the last commit; null while nothing is pending.
  const draftRef = useRef<string | null>(null);
  // The value this field itself last wrote, so its own commits are not
  // mistaken for external changes.
  const ownCommitRef = useRef<string | null>(null);
  // Bumped to remount the select, which resets its visible text.
  const [resyncKey, setResyncKey] = useState(0);

  const seenRef = useRef({ committed, initialValues });
  useEffect(() => {
    const seen = seenRef.current;
    if (seen.committed === committed && seen.initialValues === initialValues) {
      return;
    }
    const ownCommit =
      seen.initialValues === initialValues &&
      ownCommitRef.current !== null &&
      ownCommitRef.current === committed;
    seenRef.current = { committed, initialValues };
    ownCommitRef.current = null;
    if (!ownCommit && draftRef.current !== null) {
      draftRef.current = null;
      setResyncKey((key) => key + 1);
    }
  }, [committed, initialValues]);

  const commit = (next: string) => {
    draftRef.current = null;
    ownCommitRef.current = next;
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
        key={resyncKey}
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
