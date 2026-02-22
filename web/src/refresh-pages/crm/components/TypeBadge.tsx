import { CrmOrganizationType } from "@/app/app/crm/crmService";
import { cn } from "@/lib/utils";

const TYPE_CONFIG: Record<
  CrmOrganizationType,
  { bg: string; text: string; dot: string }
> = {
  customer: {
    bg: "bg-green-50",
    text: "text-green-700",
    dot: "bg-green-500",
  },
  prospect: {
    bg: "bg-blue-50",
    text: "text-blue-700",
    dot: "bg-blue-500",
  },
  partner: {
    bg: "bg-purple-50",
    text: "text-purple-700",
    dot: "bg-purple-500",
  },
  vendor: {
    bg: "bg-orange-50",
    text: "text-orange-700",
    dot: "bg-orange-500",
  },
  other: {
    bg: "bg-gray-100",
    text: "text-gray-600",
    dot: "bg-gray-400",
  },
};

interface TypeBadgeProps {
  type: CrmOrganizationType | null;
}

export default function TypeBadge({ type }: TypeBadgeProps) {
  if (!type) return null;
  const config = TYPE_CONFIG[type] || TYPE_CONFIG.other;
  const label = type.charAt(0).toUpperCase() + type.slice(1);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-sm font-medium",
        config.bg,
        config.text
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", config.dot)} />
      {label}
    </span>
  );
}
