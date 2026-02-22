import { cn } from "@/lib/utils";
import { formatCrmLabel } from "@/refresh-pages/crm/crmOptions";

interface StatusColorConfig {
  bg: string;
  text: string;
  dot: string;
}

const STATUS_CONFIG: Record<string, StatusColorConfig> = {
  lead: {
    bg: "bg-status-info-00",
    text: "text-status-text-info-05",
    dot: "bg-status-info-05",
  },
  active: {
    bg: "bg-status-success-00",
    text: "text-status-text-success-05",
    dot: "bg-status-success-05",
  },
  inactive: {
    bg: "bg-status-warning-00",
    text: "text-status-text-warning-05",
    dot: "bg-status-warning-05",
  },
  archived: {
    bg: "bg-background-neutral-02",
    text: "text-text-03",
    dot: "bg-border-03",
  },
};

const STATUS_COLOR_FALLBACKS: [StatusColorConfig, ...StatusColorConfig[]] = [
  {
    bg: "bg-status-info-00",
    text: "text-status-text-info-05",
    dot: "bg-status-info-05",
  },
  {
    bg: "bg-status-success-00",
    text: "text-status-text-success-05",
    dot: "bg-status-success-05",
  },
  {
    bg: "bg-status-warning-00",
    text: "text-status-text-warning-05",
    dot: "bg-status-warning-05",
  },
  {
    bg: "bg-background-tint-02",
    text: "text-action-text-link-05",
    dot: "bg-action-link-05",
  },
];

function hashStage(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

function getStatusColorConfig(status: string): StatusColorConfig {
  const normalized = status.trim().toLowerCase();
  if (STATUS_CONFIG[normalized]) {
    return STATUS_CONFIG[normalized];
  }
  return (
    STATUS_COLOR_FALLBACKS[
      hashStage(normalized) % STATUS_COLOR_FALLBACKS.length
    ] || STATUS_COLOR_FALLBACKS[0]
  );
}

interface StatusBadgeProps {
  status: string;
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = getStatusColorConfig(status);
  const label = formatCrmLabel(status);

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
