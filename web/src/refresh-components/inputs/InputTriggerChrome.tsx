"use client";

import type * as React from "react";
import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";
import { SvgChevronDownSmall } from "@opal/icons";
import Truncated from "@/refresh-components/texts/Truncated";
import {
  iconClasses,
  textClasses,
  Variants,
  wrapperClasses,
} from "@/refresh-components/inputs/styles";

/**
 * Classes for the outer element of an input-style trigger. The element must
 * set `data-state="open"` while its menu is open (Radix triggers do this), so
 * the border and the chevron can react.
 */
export function inputTriggerClasses(variant: Variants): string {
  return cn(
    "group/InputTrigger flex w-full items-center justify-between p-1.5 rounded-08 focus:outline-hidden",
    wrapperClasses[variant],
    variant === "primary" && "data-[state=open]:border-border-05"
  );
}

interface InputTriggerValueProps {
  variant: Variants;
  icon?: React.FunctionComponent<IconProps>;
  /** Turns off the tooltip that shows the full text when it is truncated. */
  disableTooltip?: boolean;
  children: React.ReactNode;
}

/** An optional icon and a one-line value, as a select shows its selection. */
export function InputTriggerValue({
  variant,
  icon: Icon,
  disableTooltip,
  children,
}: InputTriggerValueProps) {
  return (
    <div className="flex flex-row items-center gap-2 flex-1 w-full">
      {Icon && <Icon className={cn("h-4 w-4", iconClasses[variant])} />}
      <Truncated className={cn(textClasses[variant])} disable={disableTooltip}>
        {children}
      </Truncated>
    </div>
  );
}

interface InputTriggerChromeProps {
  variant: Variants;
  /** Content to show before the chevron. */
  rightSection?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * The inside of an input-style trigger: the content, an optional right
 * section, and a chevron that turns while the menu is open. Put it in an
 * element that uses `inputTriggerClasses`.
 */
export default function InputTriggerChrome({
  variant,
  rightSection,
  children,
}: InputTriggerChromeProps) {
  return (
    <div className="flex flex-row items-center justify-between w-full p-0.5 gap-1">
      {children}

      <div className="flex flex-row items-center gap-1">
        {rightSection}

        <SvgChevronDownSmall
          aria-hidden
          className={cn(
            "h-4 w-4 transition-transform",
            iconClasses[variant],
            "group-data-[state=open]/InputTrigger:-rotate-180"
          )}
        />
      </div>
    </div>
  );
}
