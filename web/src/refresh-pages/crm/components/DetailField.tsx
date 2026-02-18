import { Route } from "next";
import Link from "next/link";

import { cn } from "@/lib/utils";

import { SvgExternalLink } from "@opal/icons";

interface DetailFieldProps {
  label: string;
  value: string | null | undefined;
  type?: "text" | "email" | "phone" | "link" | "org-link";
  href?: string;
  layout?: "inline" | "stacked";
}

export default function DetailField({
  label,
  value,
  type = "text",
  href,
  layout = "inline",
}: DetailFieldProps) {
  const wrapperClassName =
    layout === "stacked" ? "flex flex-col gap-0.5" : "flex items-start gap-2";
  const labelClassName =
    layout === "stacked"
      ? "select-none"
      : "w-[105px] shrink-0 select-none pt-0.5";

  const valueBase = "text-sm font-medium text-text-05";

  function renderValue() {
    if (!value) {
      return <span className="text-sm italic text-text-03">-</span>;
    }

    switch (type) {
      case "email":
        return (
          <a
            href={`mailto:${value}`}
            className={cn(valueBase, "break-all hover:underline")}
          >
            {value}
          </a>
        );
      case "phone":
        return (
          <a
            href={`tel:${value}`}
            className={cn(valueBase, "hover:underline")}
          >
            {value}
          </a>
        );
      case "link":
        return (
          <a
            href={value.startsWith("http") ? value : `https://${value}`}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              valueBase,
              "inline-flex items-center gap-1 break-all hover:underline"
            )}
          >
            {value}
            <SvgExternalLink size={12} className="shrink-0" />
          </a>
        );
      case "org-link":
        return href ? (
          <Link
            href={href as Route}
            className={cn(valueBase, "hover:underline")}
          >
            {value}
          </Link>
        ) : (
          <span className={valueBase}>{value}</span>
        );
      default:
        return <span className={valueBase}>{value}</span>;
    }
  }

  return (
    <div className={wrapperClassName}>
      <span className={cn("text-sm text-text-03", labelClassName)}>
        {label}
      </span>
      <div className="min-w-0 flex-1">{renderValue()}</div>
    </div>
  );
}
