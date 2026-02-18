import { CrmInteractionType } from "@/app/app/crm/crmService";

import { SvgBubbleText, SvgCalendar, SvgFileText, SvgHeadsetMic, SvgUsers } from "@opal/icons";
import type { IconProps } from "@opal/types";

const INTERACTION_ICONS: Record<
  CrmInteractionType,
  React.FunctionComponent<IconProps>
> = {
  note: SvgFileText,
  call: SvgHeadsetMic,
  email: SvgBubbleText,
  meeting: SvgUsers,
  event: SvgCalendar,
};

interface InteractionTypeIconProps {
  type: CrmInteractionType;
  size?: number;
  className?: string;
}

export default function InteractionTypeIcon({
  type,
  size = 16,
  className = "stroke-text-03",
}: InteractionTypeIconProps) {
  const Icon = INTERACTION_ICONS[type] || SvgFileText;
  return <Icon size={size} className={className} />;
}
