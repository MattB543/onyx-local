"use client";

import { useState } from "react";
import { useLocale } from "next-intl";

import { isAfterDate, normalizeDate } from "@/lib/dateUtils";
import { Button, InputDatePicker, Popover } from "@opal/components";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTriggerChrome, {
  inputTriggerClasses,
  InputTriggerValue,
} from "@/refresh-components/inputs/InputTriggerChrome";
import Text from "@/refresh-components/texts/Text";
import { SvgCalendar } from "@opal/icons";
import { cn } from "@opal/utils";

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

/**
 * Short trigger label, for example "Created: Sep 1 – Sep 23". The dates show
 * the year only when one of them is not in the year of `now`.
 */
export function formatDateRangeLabel(
  value: CrmDateRangeValue,
  locale: string,
  now: Date = new Date()
): string {
  const prefix = value.field === "created" ? "Created" : "Updated";
  const { from, to } = value;
  const showYear = [from, to].some(
    (date) => date !== null && date.getFullYear() !== now.getFullYear()
  );
  const formatter = new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    year: showYear ? "numeric" : undefined,
  });
  if (from && to) {
    return `${prefix}: ${formatter.format(from)} – ${formatter.format(to)}`;
  }
  if (from) {
    return `${prefix}: from ${formatter.format(from)}`;
  }
  if (to) {
    return `${prefix}: until ${formatter.format(to)}`;
  }
  return `${prefix}: any date`;
}

export default function CrmDateRangeFilter({
  value,
  onChange,
}: CrmDateRangeFilterProps) {
  const locale = useLocale();
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

  const label = formatDateRangeLabel(value, locale);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        {/* raw-ok: an input-style trigger that matches InputSelect; Opal Button has no input look */}
        <button
          type="button"
          title={label}
          className={cn(inputTriggerClasses("primary"), "md:w-[240px]")}
        >
          <InputTriggerChrome variant="primary">
            {/* The title attribute already shows the full label. */}
            <InputTriggerValue
              variant="primary"
              icon={SvgCalendar}
              disableTooltip
            >
              {label}
            </InputTriggerValue>
          </InputTriggerChrome>
        </button>
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
                value={value.from}
                onChange={handleFromChange}
                maxDate={today}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Text as="p" text03 className="text-xs">
                To
              </Text>
              <InputDatePicker
                value={value.to}
                onChange={handleToChange}
                minDate={value.from ?? undefined}
                maxDate={today}
              />
            </div>
          </div>

          <div className="flex justify-end">
            <Button
              variant="action"
              prominence="tertiary"
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
