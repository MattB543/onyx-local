import { cn } from "@/lib/utils";

const AVATAR_COLORS = [
  { bg: "bg-blue-100", text: "text-blue-700" },
  { bg: "bg-green-100", text: "text-green-700" },
  { bg: "bg-purple-100", text: "text-purple-700" },
  { bg: "bg-orange-100", text: "text-orange-700" },
  { bg: "bg-pink-100", text: "text-pink-700" },
  { bg: "bg-teal-100", text: "text-teal-700" },
  { bg: "bg-indigo-100", text: "text-indigo-700" },
  { bg: "bg-rose-100", text: "text-rose-700" },
];

const sizeClasses = {
  sm: "w-8 h-8 text-xs",
  md: "w-10 h-10 text-sm",
  lg: "w-12 h-12 text-base",
};

interface ContactAvatarProps {
  firstName: string;
  lastName: string | null;
  size?: "sm" | "md" | "lg";
}

export default function ContactAvatar({
  firstName,
  lastName,
  size = "md",
}: ContactAvatarProps) {
  const initials = (
    (firstName?.[0] || "") + (lastName?.[0] || "")
  ).toUpperCase();
  const colorIndex =
    ((firstName?.charCodeAt(0) || 0) + (lastName?.charCodeAt(0) || 0)) %
    AVATAR_COLORS.length;
  // colorIndex is always valid (modulo AVATAR_COLORS.length)
  const color = AVATAR_COLORS[colorIndex]!;

  return (
    <div
      className={cn(
        "flex shrink-0 select-none items-center justify-center rounded-full font-medium",
        sizeClasses[size],
        color.bg,
        color.text
      )}
    >
      {initials || "?"}
    </div>
  );
}
