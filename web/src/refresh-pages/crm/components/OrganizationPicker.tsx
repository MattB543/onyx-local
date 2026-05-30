"use client";

import { useDeferredValue, useMemo } from "react";

import { useCrmOrganization } from "@/lib/hooks/useCrmOrganization";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import InputComboBox, {
  ComboBoxOption,
} from "@/refresh-components/inputs/InputComboBox";
import Text from "@/refresh-components/texts/Text";

interface OrganizationPickerProps {
  selectedOrganizationId: string | null;
  inputValue: string;
  onInputChange: (value: string) => void;
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
  onInputChange,
  onOrganizationChange,
  placeholder = "Organization",
  disabled = false,
}: OrganizationPickerProps) {
  const deferredQuery = useDeferredValue(inputValue);
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

  const options = useMemo<ComboBoxOption[]>(
    () =>
      Array.from(optionMetadataByValue.values()).map((metadata) => ({
        value: metadata.displayValue,
        label: metadata.displayValue,
      })),
    [optionMetadataByValue]
  );

  const resolvedValue =
    selectedOrganizationId &&
    displayValueByOrganizationId.has(selectedOrganizationId)
      ? displayValueByOrganizationId.get(selectedOrganizationId) || ""
      : inputValue;

  const isLoading =
    areOrganizationsLoading ||
    (Boolean(selectedOrganizationId) && isSelectedLoading);

  return (
    <div className="flex w-full flex-col gap-1">
      <InputComboBox
        value={resolvedValue}
        onChange={(event) => {
          onInputChange(event.target.value);
        }}
        onValueChange={(organizationDisplayValue) => {
          const metadata = optionMetadataByValue.get(organizationDisplayValue);
          onOrganizationChange(
            metadata?.id ?? null,
            metadata?.name ?? organizationDisplayValue
          );
        }}
        onClear={() => {
          onOrganizationChange(null, "");
        }}
        options={options}
        placeholder={placeholder}
        strict
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
