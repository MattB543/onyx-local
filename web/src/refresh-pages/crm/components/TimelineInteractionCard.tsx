import { CrmInteraction } from "@/app/app/crm/crmService";
import Text from "@/refresh-components/texts/Text";

import { formatTime } from "./crmDateUtils";
import InteractionTypeIcon from "./InteractionTypeIcon";

interface TimelineInteractionCardProps {
  interaction: CrmInteraction;
  attendeeUserNameById?: Map<string, string>;
  attendeeContactNameById?: Map<string, string>;
}

export default function TimelineInteractionCard({
  interaction,
  attendeeUserNameById,
  attendeeContactNameById,
}: TimelineInteractionCardProps) {
  const timeLabel = formatTime(
    interaction.occurred_at || interaction.created_at
  );
  const typeLabel =
    interaction.type.charAt(0).toUpperCase() + interaction.type.slice(1);
  const attendeeNames = Array.from(
    new Set(
      interaction.attendees
        .map((attendee) => {
          const providedName = attendee.display_name?.trim();
          if (providedName) {
            return providedName;
          }

          if (attendee.user_id) {
            return attendeeUserNameById?.get(attendee.user_id)?.trim() || null;
          }

          if (attendee.contact_id) {
            return (
              attendeeContactNameById?.get(attendee.contact_id)?.trim() || null
            );
          }

          return null;
        })
        .filter((name): name is string => Boolean(name))
    )
  );

  return (
    <div className="relative mb-4 ml-0 flex gap-3">
      <div className="relative z-10 flex w-[31px] shrink-0 justify-center">
        <div className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-background-tint-02">
          <InteractionTypeIcon type={interaction.type} />
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <Text as="p" mainUiAction text05>
          {interaction.title}
        </Text>
        <Text as="p" secondaryBody text05 className="text-sm">
          {timeLabel}
          {timeLabel && " \u00B7 "}
          {typeLabel}
        </Text>
        {interaction.summary && (
          <Text
            as="p"
            secondaryBody
            text05
            className="mt-1 line-clamp-2 text-sm"
          >
            {interaction.summary}
          </Text>
        )}
        {attendeeNames.length > 0 && (
          <Text
            as="p"
            secondaryBody
            text05
            className="mt-1 line-clamp-2 text-sm"
          >
            {attendeeNames.join(", ")}
          </Text>
        )}
      </div>
    </div>
  );
}
