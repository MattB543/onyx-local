import { CrmInteraction } from "@/app/app/crm/crmService";
import Text from "@/refresh-components/texts/Text";

import { formatTime } from "./crmDateUtils";
import InteractionTypeIcon from "./InteractionTypeIcon";

interface TimelineInteractionCardProps {
  interaction: CrmInteraction;
}

export default function TimelineInteractionCard({
  interaction,
}: TimelineInteractionCardProps) {
  const timeLabel = formatTime(
    interaction.occurred_at || interaction.created_at
  );
  const typeLabel =
    interaction.type.charAt(0).toUpperCase() + interaction.type.slice(1);

  return (
    <div className="relative mb-4 ml-0 flex gap-3">
      <div className="relative z-10 flex w-[31px] shrink-0 justify-center">
        <div className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-background-tint-02">
          <InteractionTypeIcon type={interaction.type} />
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <Text as="p" mainUiAction text02>
          {interaction.title}
        </Text>
        <Text as="p" secondaryBody text03>
          {timeLabel}
          {timeLabel && " \u00B7 "}
          {typeLabel}
        </Text>
        {interaction.summary && (
          <Text as="p" secondaryBody text03 className="mt-1 line-clamp-2">
            {interaction.summary}
          </Text>
        )}
      </div>
    </div>
  );
}
