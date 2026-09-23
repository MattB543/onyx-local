import { cn } from "@opal/utils";
import { formatPrincipalOffice } from "@/views/crm/crmOptions";

interface ContactRoleLineProps {
  title: string | null;
  organizationName: string | null;
  principal: string | null;
}

/** "<title> at <org> · Office of <principal>" for contact cards. */
export default function ContactRoleLine({
  title,
  organizationName,
  principal,
}: ContactRoleLineProps) {
  const role = title
    ? organizationName
      ? `${title} at ${organizationName}`
      : title
    : organizationName
      ? `at ${organizationName}`
      : null;
  const office = principal?.trim() ? formatPrincipalOffice(principal) : null;

  if (!role && !office) {
    return <span className="truncate text-sm text-text-03">No title</span>;
  }

  return (
    <div
      className="flex min-w-0 items-center gap-1 text-sm text-text-03"
      title={[role, office].filter(Boolean).join(" · ")}
    >
      {role && <span className="min-w-0 truncate">{role}</span>}
      {role && office && <span className="shrink-0">·</span>}
      {office && (
        // Keep the office visible when a long title/org has to truncate.
        <span className={cn("shrink-0 truncate", role && "max-w-[60%]")}>
          {office}
        </span>
      )}
    </div>
  );
}
