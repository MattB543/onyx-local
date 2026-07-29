"use client";

import { useState } from "react";

import {
  getFormattedDateRangeString,
  isAfterDate,
  normalizeDate,
} from "@/lib/dateUtils";
import Button from "@/refresh-components/buttons/Button";
import InputDatePicker from "@/refresh-components/inputs/InputDatePicker";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import { Popover } from "@opal/components";
import { SvgCalendar } from "@opal/icons";

export type CrmDateField = "created" | "updated";

export interface CrmDateRangeValue {
  field: CrmDateField;
  from: Date | null;
  to: Date | null;
}

interface CrmDateRangeFilterProps {
  value: CrmDateRangeValue;
  onChange: (next: CrmDateRangeValue) => void;
}

/**
 * Returns an ISO 8601 string for the start of the given local day
 * (00:00:00.000).
 */
function startOfDayIso(date: Date): string {
  return normalizeDate(date).toISOString();
}

/**
 * Returns an ISO 8601 string for the end of the given local day
 * (23:59:59.999). Used for the inclusive "To" upper bound so that records
 * created/updated anytime on the selected day are included.
 */
function endOfDayIso(date: Date): string {
  const end = new Date(date);
  end.setHours(23, 59, 59, 999);
  return end.toISOString();
}

/**
 * Pure mapper from the date-range UI value to the backend query params.
 * Only the params for the selected field are populated.
 */
export function dateRangeToParams(v: CrmDateRangeValue): {
  created_after?: string;
  created_before?: string;
  updated_after?: string;
  updated_before?: string;
} {
  const fromIso = v.from ? startOfDayIso(v.from) : undefined;
  const toIso = v.to ? endOfDayIso(v.to) : undefined;
  if (v.field === "created") {
    return { created_after: fromIso, created_before: toIso };
  }
  return { updated_after: fromIso, updated_before: toIso };
}

function buildTriggerLabel(value: CrmDateRangeValue): string {
  const prefix = value.field === "created" ? "Created" : "Updated";
  const range = getFormattedDateRangeString(value.from, value.to);
  if (range) {
    return `${prefix}: ${range}`;
  }
  if (value.from) {
    return `${prefix}: from ${value.from.toLocaleDateString()}`;
  }
  if (value.to) {
    return `${prefix}: until ${value.to.toLocaleDateString()}`;
  }
  return `${prefix}: any date`;
}

export default function CrmDateRangeFilter({
  value,
  onChange,
}: CrmDateRangeFilterProps) {
  const [open, setOpen] = useState(false);
  const today = new Date();

  function handleFieldChange(field: CrmDateField) {
    onChange({ ...value, field });
  }

  function handleFromChange(from: Date | null) {
    // If the new "from" is after the existing "to", clear "to" to keep a
    // valid range.
    const to =
      from && value.to && isAfterDate(from, value.to) ? null : value.to;
    onChange({ ...value, from, to });
  }

  function handleToChange(to: Date | null) {
    // Ignore a "to" that is before "from".
    if (to && value.from && isAfterDate(value.from, to)) {
      return;
    }
    onChange({ ...value, to });
  }

  function handleClear() {
    onChange({ ...value, from: null, to: null });
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <Button action secondary leftIcon={SvgCalendar}>
          {buildTriggerLabel(value)}
        </Button>
      </Popover.Trigger>
      <Popover.Content align="start">
        <div className="flex flex-col gap-3 p-1">
          <InputSelect
            value={value.field}
            onValueChange={(next) => handleFieldChange(next as CrmDateField)}
          >
            <InputSelect.Trigger placeholder="Date field" />
            <InputSelect.Content>
              <InputSelect.Item value="created">Created</InputSelect.Item>
              <InputSelect.Item value="updated">Updated</InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>

          <div className="flex flex-row items-center gap-2">
            <div className="flex flex-col gap-1">
              <Text as="p" text03 className="text-xs">
                From
              </Text>
              <InputDatePicker
                selectedDate={value.from}
                setSelectedDate={handleFromChange}
                maxDate={today}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Text as="p" text03 className="text-xs">
                To
              </Text>
              <InputDatePicker
                selectedDate={value.to}
                setSelectedDate={handleToChange}
                maxDate={today}
              />
            </div>
          </div>

          <div className="flex justify-end">
            <Button
              action
              tertiary
              size="md"
              onClick={handleClear}
              disabled={!value.from && !value.to}
            >
              Clear dates
            </Button>
          </div>
        </div>
      </Popover.Content>
    </Popover>
  );
}
