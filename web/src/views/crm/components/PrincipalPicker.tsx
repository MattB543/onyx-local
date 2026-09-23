"use client";

import { useDeferredValue, useMemo } from "react";

import { useCrmContactPrincipals } from "@/lib/hooks/useCrmContactPrincipals";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { Text } from "@opal/components";
import InputComboBox, {
  ComboBoxOption,
} from "@/refresh-components/inputs/InputComboBox";

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
  placeholder: string;
}

/** Principal field that suggests both contact records (to link the official)
 * and the principal names other contacts already use. */
export default function PrincipalPicker({
  principal,
  principalContactId,
  onChange,
  excludeContactId,
  placeholder,
}: PrincipalPickerProps) {
  const { principalOptions } = useCrmContactPrincipals();
  const query = useDeferredValue(principal.trim());
  // A name match, so the official's staff (whose principal also matches)
  // cannot crowd the official out of the results.
  const { contacts } = useCrmContacts({
    name: query || undefined,
    pageNum: 0,
    pageSize: CONTACT_OPTION_LIMIT,
  });

  const contactOptions = useMemo<ComboBoxOption[]>(() => {
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

  const options = useMemo(
    () => [...contactOptions, ...principalOptions],
    [contactOptions, principalOptions]
  );

  return (
    <div className="flex w-full flex-col gap-1">
      <InputComboBox
        value={
          principalContactId
            ? `${CONTACT_OPTION_PREFIX}${principalContactId}`
            : principal
        }
        // InputComboBox calls onChange for typing and for every picked
        // option, then onValueChange for picked options only.
        onChange={(event) => {
          if (!event.target.value.startsWith(CONTACT_OPTION_PREFIX)) {
            onChange(event.target.value, null);
          }
        }}
        onValueChange={(value) => {
          if (!value.startsWith(CONTACT_OPTION_PREFIX)) {
            return;
          }
          const option = contactOptions.find((item) => item.value === value);
          onChange(
            option?.label ?? principal,
            value.slice(CONTACT_OPTION_PREFIX.length)
          );
        }}
        options={options}
        strict={false}
        placeholder={placeholder}
      />
      {principalContactId && (
        <Text as="p" font="secondary-body" color="text-03">
          Linked to the official&apos;s contact record.
        </Text>
      )}
    </div>
  );
}
