"use client";

import { useDeferredValue, useMemo, useState } from "react";

import { useCrmOrganization } from "@/lib/hooks/useCrmOrganization";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import { InputSingleSelect, type SelectOption } from "@opal/components";
import Text from "@/refresh-components/texts/Text";

interface OrganizationPickerProps {
  selectedOrganizationId: string | null;
  /** Name of the selected organization, shown while its record loads. */
  inputValue: string;
  onOrganizationChange: (
    organizationId: string | null,
    organizationName: string
  ) => void;
  placeholder?: string;
  disabled?: boolean;
}

export default function OrganizationPicker({
  selectedOrganizationId,
  inputValue,
  onOrganizationChange,
  placeholder = "Organization",
  disabled = false,
}: OrganizationPickerProps) {
  // Typed text only drives the server-side search. The select is a closed
  // set: abandoning a search reverts to the committed organization, and only
  // a pick (or clearing the field) reaches the parent.
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const { organization: selectedOrganization, isLoading: isSelectedLoading } =
    useCrmOrganization(selectedOrganizationId);
  const {
    organizations,
    error,
    isLoading: areOrganizationsLoading,
  } = useCrmOrganizations({
    q: deferredQuery || undefined,
    pageNum: 0,
    pageSize: 50,
  });

  const organizationsById = useMemo(() => {
    const entries = new Map<
      string,
      {
        id: string;
        name: string;
      }
    >();

    if (selectedOrganization?.id) {
      entries.set(selectedOrganization.id, {
        id: selectedOrganization.id,
        name: selectedOrganization.name,
      });
    }

    organizations.forEach((organization) => {
      entries.set(organization.id, {
        id: organization.id,
        name: organization.name,
      });
    });

    return entries;
  }, [organizations, selectedOrganization]);

  const optionMetadataByValue = useMemo(() => {
    const nameCounts = new Map<string, number>();
    organizationsById.forEach((organization) => {
      nameCounts.set(
        organization.name,
        (nameCounts.get(organization.name) ?? 0) + 1
      );
    });

    const entries = new Map<
      string,
      {
        id: string;
        name: string;
        displayValue: string;
      }
    >();

    organizationsById.forEach((organization) => {
      const hasCollision = (nameCounts.get(organization.name) ?? 0) > 1;
      const displayValue = hasCollision
        ? `${organization.name} (${organization.id.slice(0, 8)})`
        : organization.name;

      entries.set(displayValue, {
        id: organization.id,
        name: organization.name,
        displayValue,
      });
    });

    return entries;
  }, [organizationsById]);

  const displayValueByOrganizationId = useMemo(() => {
    const entries = new Map<string, string>();
    optionMetadataByValue.forEach((metadata) => {
      entries.set(metadata.id, metadata.displayValue);
    });
    return entries;
  }, [optionMetadataByValue]);

  const options = useMemo<SelectOption[]>(
    () =>
      Array.from(optionMetadataByValue.values()).map((metadata) => ({
        value: metadata.displayValue,
        label: metadata.displayValue,
      })),
    [optionMetadataByValue]
  );

  const resolvedValue = selectedOrganizationId
    ? (displayValueByOrganizationId.get(selectedOrganizationId) ?? inputValue)
    : "";

  const isLoading =
    areOrganizationsLoading ||
    (Boolean(selectedOrganizationId) && isSelectedLoading);

  return (
    <div className="flex w-full flex-col gap-1">
      <InputSingleSelect
        value={resolvedValue}
        onChange={(event) => {
          const text = event.target.value;
          setQuery(text);
          // Emptying the field clears the organization.
          if (!text && selectedOrganizationId) {
            onOrganizationChange(null, "");
          }
        }}
        onValueChange={(organizationDisplayValue) => {
          setQuery("");
          // Re-picking the selected org toggles it off and emits "", which
          // resolves to no metadata: that clears the organization.
          const metadata = optionMetadataByValue.get(organizationDisplayValue);
          onOrganizationChange(
            metadata?.id ?? null,
            metadata?.name ?? organizationDisplayValue
          );
        }}
        options={options}
        placeholder={placeholder}
        // While the selected organization's record loads, `value` falls back
        // to its name, which is not an option yet; don't flash a closed-set
        // validation error for it.
        isError={false}
        disabled={disabled}
        searchIcon
      />
      {isLoading && (
        <Text as="p" secondaryBody text03 className="text-sm">
          Loading organizations...
        </Text>
      )}
      {error && (
        <Text as="p" secondaryBody className="text-sm text-status-error-03">
          Failed to load organizations.
        </Text>
      )}
    </div>
  );
}
