"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";

import { useCrmContactPrincipals } from "@/lib/hooks/useCrmContactPrincipals";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { InputSingleSelect, Text, type SelectOption } from "@opal/components";

// Contact options carry this prefix, so they never collide with principal text.
const CONTACT_OPTION_PREFIX = "contact:";
const CONTACT_OPTION_LIMIT = 25;

interface PrincipalPickerProps {
  principal: string;
  principalContactId: string | null;
  /** Picking a contact links it and uses its name. Typing or picking an
   * existing principal name removes the link. */
  onChange: (principal: string, principalContactId: string | null) => void;
  /** The contact being edited; a contact cannot be its own principal. */
  excludeContactId?: string;
  /** The contact's own name: hidden from the principal-name suggestions only,
   * so it can still be typed by hand (names are not unique). */
  excludeName?: string;
  placeholder: string;
}

/** Principal field that suggests both contact records (to link the official)
 * and the principal names other contacts already use.
 *
 * An open-set `InputSingleSelect`. As in `OrganizationPicker`, typed text only
 * drives the contact search; as in `CrmCategoryField`, it is a local draft and
 * never the select's `value` (Enter on a matching option would otherwise
 * toggle it off):
 * - picking a contact, a principal name or the create row commits it; picking
 *   the current selection again toggles it off and clears the principal;
 * - leaving the field commits a changed draft as free text (unlinking any
 *   contact), and an emptied field clears the principal;
 * - Escape and the chevron discard the draft. */
export default function PrincipalPicker({
  principal,
  principalContactId,
  onChange,
  excludeContactId,
  excludeName,
  placeholder,
}: PrincipalPickerProps) {
  const { principalOptions } = useCrmContactPrincipals();
  // Text typed since the last commit; null while nothing is pending.
  const draftRef = useRef<string | null>(null);
  const [typedText, setTypedText] = useState("");
  // Bumped to remount the select, which resets its visible text.
  const [resyncKey, setResyncKey] = useState(0);

  // Search by what is being typed, or else by the current principal, so an
  // unlinked name already offers its matching contact records.
  const query = useDeferredValue((typedText || principal).trim());
  // A name match, so the official's staff (whose principal also matches)
  // cannot crowd the official out of the results.
  const { contacts } = useCrmContacts({
    name: query || undefined,
    pageNum: 0,
    pageSize: CONTACT_OPTION_LIMIT,
  });

  const contactOptions = useMemo<SelectOption[]>(() => {
    const candidates = query
      ? contacts.filter(
          (contact) => contact.id !== excludeContactId && contact.full_name
        )
      : [];
    const options = candidates.map((contact) => ({
      value: `${CONTACT_OPTION_PREFIX}${contact.id}`,
      label: contact.full_name,
      description: ["Contact record", contact.title, contact.organization_name]
        .filter(Boolean)
        .join(" · "),
    }));
    // Keep the linked contact selectable and labelled while results load.
    if (
      principalContactId &&
      !candidates.some((contact) => contact.id === principalContactId)
    ) {
      options.unshift({
        value: `${CONTACT_OPTION_PREFIX}${principalContactId}`,
        label: principal,
        description: "Contact record",
      });
    }
    return options;
  }, [contacts, query, excludeContactId, principalContactId, principal]);

  const options = useMemo(() => {
    const excluded = excludeName?.trim().toLowerCase();
    const principalSuggestions = excluded
      ? principalOptions.filter(
          (option) => option.value.trim().toLowerCase() !== excluded
        )
      : principalOptions;
    return [...contactOptions, ...principalSuggestions];
  }, [contactOptions, principalOptions, excludeName]);

  const value = principalContactId
    ? `${CONTACT_OPTION_PREFIX}${principalContactId}`
    : principal;

  // Own commits clear the draft first, so a pending draft at a value change
  // means the parent changed it (e.g. the form reset): drop the stale draft
  // so it cannot overwrite the new value on the next blur.
  const seenValueRef = useRef(value);
  useEffect(() => {
    if (seenValueRef.current === value) return;
    seenValueRef.current = value;
    if (draftRef.current !== null) {
      draftRef.current = null;
      setTypedText("");
      setResyncKey((key) => key + 1);
    }
  }, [value]);

  const discardDraft = () => {
    draftRef.current = null;
    setTypedText("");
  };

  const handleBlur = (event: React.FocusEvent<HTMLDivElement>) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;

    // Focus moving into our own (portaled) dropdown is not "leaving": an
    // option click commits on its own.
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
    discardDraft();

    const trimmed = draft.trim();
    const lowered = trimmed.toLowerCase();
    // Unchanged text keeps a linked contact linked.
    if (lowered === principal.trim().toLowerCase()) return;
    // Typing never links a contact; snap to an existing principal's spelling.
    const matched = trimmed
      ? principalOptions.find(
          (option) => option.value.toLowerCase() === lowered
        )
      : undefined;
    onChange(matched?.value ?? trimmed, null);
  };

  return (
    <div className="flex w-full flex-col gap-1">
      <div
        role="presentation"
        className="w-full"
        onBlur={handleBlur}
        onKeyDownCapture={(event) => {
          if (event.key === "Escape") discardDraft();
        }}
        onClickCapture={(event) => {
          const target = event.target;
          const button =
            target instanceof Element ? target.closest("button") : null;
          if (button && event.currentTarget.contains(button)) discardDraft();
        }}
      >
        <InputSingleSelect
          key={resyncKey}
          mode="open"
          value={value}
          // Fires per keystroke (and once, synthetically, before
          // onValueChange on a pick): track the draft only.
          onChange={(event) => {
            draftRef.current = event.target.value;
            setTypedText(event.target.value);
          }}
          onValueChange={(picked) => {
            discardDraft();
            if (picked.startsWith(CONTACT_OPTION_PREFIX)) {
              const option = contactOptions.find(
                (item) => item.value === picked
              );
              onChange(
                option?.label ?? principal,
                picked.slice(CONTACT_OPTION_PREFIX.length)
              );
              return;
            }
            // A principal name, the create row, or "" when re-picking the
            // selection toggles it off.
            onChange(picked, null);
          }}
          options={options}
          placeholder={placeholder}
        />
      </div>
      {principalContactId && (
        <Text as="p" font="secondary-body" color="text-03">
          Linked to the official&apos;s contact record.
        </Text>
      )}
    </div>
  );
}
