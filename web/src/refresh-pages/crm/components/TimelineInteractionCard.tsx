import { CrmInteraction } from "@/app/app/crm/crmService";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";

import { SvgTrash } from "@opal/icons";

import { formatDateTime } from "./crmDateUtils";
import InteractionTypeIcon from "./InteractionTypeIcon";

interface TimelineInteractionCardProps {
  interaction: CrmInteraction;
  attendeeUserNameById?: Map<string, string>;
  attendeeContactNameById?: Map<string, string>;
  canDelete?: boolean;
  onDelete?: () => void;
}

export default function TimelineInteractionCard({
  interaction,
  attendeeUserNameById,
  attendeeContactNameById,
  canDelete = false,
  onDelete,
}: TimelineInteractionCardProps) {
  const dateTimeLabel = formatDateTime(
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

  const people = [
    interaction.contact_name,
    ...attendeeNames,
  ].filter(Boolean);

  return (
    <div>
      <div className="group relative mb-3 ml-0 flex gap-3 pr-10">
        <div className="relative z-[1] flex w-[31px] shrink-0 justify-center">
          <div className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-background-tint-02">
            <InteractionTypeIcon type={interaction.type} />
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <Text as="p" mainUiAction text05>
            {interaction.title}
          </Text>
          <Text as="p" secondaryBody text05 className="text-sm">
            {dateTimeLabel}
            {people.length > 0 && ` \u00B7 ${people.join(", ")}`}
            {` \u00B7 ${typeLabel}`}
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
        </div>
        {canDelete && onDelete && (
          <div className="absolute right-0 top-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            <IconButton
              main
              tertiary
              icon={SvgTrash}
              tooltip="Delete interaction"
              onClick={(event) => {
                event.stopPropagation();
                onDelete();
              }}
            />
          </div>
        )}
      </div>
      <div className="mb-3 border-t border-border-subtle" />
    </div>
  );
}
