import { CrmOrganizationType } from "@/app/app/crm/crmService";
import { cn } from "@/lib/utils";

const TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  customer: { bg: "bg-green-100", text: "text-green-700" },
  prospect: { bg: "bg-blue-100", text: "text-blue-700" },
  partner: { bg: "bg-purple-100", text: "text-purple-700" },
  vendor: { bg: "bg-orange-100", text: "text-orange-700" },
  other: { bg: "bg-gray-100", text: "text-gray-700" },
  default: { bg: "bg-gray-100", text: "text-gray-600" },
};

const sizeClasses = {
  sm: "w-8 h-8 text-xs",
  md: "w-10 h-10 text-sm",
  lg: "w-12 h-12 text-base",
};

interface OrgAvatarProps {
  name: string;
  type?: CrmOrganizationType | null;
  size?: "sm" | "md" | "lg";
}

export default function OrgAvatar({ name, type, size = "md" }: OrgAvatarProps) {
  const initial = (name?.[0] || "?").toUpperCase();
  const color = TYPE_COLORS[type || "default"] ?? TYPE_COLORS["default"]!;

  return (
    <div
      className={cn(
        "flex shrink-0 select-none items-center justify-center rounded-lg font-medium",
        sizeClasses[size],
        color.bg,
        color.text
      )}
    >
      {initial}
    </div>
  );
}
