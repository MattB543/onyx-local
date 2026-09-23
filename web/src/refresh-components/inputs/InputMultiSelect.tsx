"use client";

import { useMemo } from "react";

import { InputSingleSelect } from "@opal/components";

export interface InputMultiSelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface InputMultiSelectProps {
  value: string[];
  onChange: (nextValue: string[]) => void;
  options: InputMultiSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  allowCustom?: boolean;
}

function normalizeList(values: string[]): string[] {
  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const raw of values) {
    const candidate = raw.trim();
    if (!candidate) {
      continue;
    }
    const key = candidate.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(candidate);
  }
  return deduped;
}

export default function InputMultiSelect({
  value,
  onChange,
  options,
  placeholder = "Select options",
  disabled = false,
  allowCustom = false,
}: InputMultiSelectProps) {
  const selectedValues = useMemo(() => normalizeList(value), [value]);
  const selectedSet = useMemo(
    () => new Set(selectedValues.map((entry) => entry.toLowerCase())),
    [selectedValues]
  );

  const optionByValue = useMemo(() => {
    const byValue = new Map<string, InputMultiSelectOption>();
    for (const option of options) {
      byValue.set(option.value, option);
    }
    return byValue;
  }, [options]);

  const availableOptions = useMemo(
    () =>
      options.filter((option) => !selectedSet.has(option.value.toLowerCase())),
    [options, selectedSet]
  );

  const resolveDraftValue = (raw: string): string | null => {
    const normalized = raw.trim();
    if (!normalized) {
      return null;
    }

    if (allowCustom) {
      return normalized;
    }

    const normalizedLower = normalized.toLowerCase();
    const exactByValue = options.find(
      (option) => option.value.toLowerCase() === normalizedLower
    );
    if (exactByValue) {
      return exactByValue.value;
    }

    const exactByLabel = options.find(
      (option) => option.label.toLowerCase() === normalizedLower
    );
    if (exactByLabel) {
      return exactByLabel.value;
    }

    return null;
  };

  const appendValue = (raw: string) => {
    const resolved = resolveDraftValue(raw);
    if (!resolved) {
      return;
    }
    if (selectedSet.has(resolved.toLowerCase())) {
      return;
    }
    onChange([...selectedValues, resolved]);
  };

  const removeValue = (valueToRemove: string) => {
    const lowered = valueToRemove.toLowerCase();
    onChange(
      selectedValues.filter(
        (selectedValue) => selectedValue.toLowerCase() !== lowered
      )
    );
  };

  return (
    <div className="flex w-full flex-col gap-2">
      {selectedValues.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {selectedValues.map((selectedValue) => {
            const option = optionByValue.get(selectedValue);
            const label = option?.label || selectedValue;
            return (
              <span
                key={selectedValue}
                className="inline-flex items-center gap-1 rounded-full bg-background-tint-02 px-2 py-0.5 text-xs text-text-03"
              >
                {label}
                <button
                  type="button"
                  className="rounded-full p-0.5 text-text-03 hover:bg-background-tint-03"
                  onClick={() => removeValue(selectedValue)}
                  disabled={disabled}
                  aria-label={`Remove ${label}`}
                >
                  x
                </button>
              </span>
            );
          })}
        </div>
      )}

      <div className="w-full">
        {/* The select only picks; the chips above hold the selection. It stays
            empty (value="") like upstream's GenericMultiSelect, so typing is
            transient filter text. With allowCustom, mode="open" adds a create
            row that commits the typed text through onValueChange. */}
        <InputSingleSelect
          value=""
          onValueChange={(selectedValue) => {
            appendValue(selectedValue);
          }}
          options={availableOptions}
          mode={allowCustom ? "open" : "closed"}
          placeholder={placeholder}
          disabled={disabled}
        />
      </div>
    </div>
  );
}
