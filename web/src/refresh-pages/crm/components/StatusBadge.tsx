import { CrmContactStatus } from "@/app/app/crm/crmService";
import { cn } from "@/lib/utils";

const STATUS_CONFIG: Record<
  CrmContactStatus,
  { bg: string; text: string; dot: string }
> = {
  lead: {
    bg: "bg-blue-50",
    text: "text-blue-700",
    dot: "bg-blue-500",
  },
  active: {
    bg: "bg-green-50",
    text: "text-green-700",
    dot: "bg-green-500",
  },
  inactive: {
    bg: "bg-gray-100",
    text: "text-gray-600",
    dot: "bg-gray-400",
  },
  archived: {
    bg: "bg-gray-50",
    text: "text-gray-500",
    dot: "bg-gray-400",
  },
};

interface StatusBadgeProps {
  status: CrmContactStatus;
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.lead;
  const label = status.charAt(0).toUpperCase() + status.slice(1);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        config.bg,
        config.text
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", config.dot)} />
      {label}
    </span>
  );
}
