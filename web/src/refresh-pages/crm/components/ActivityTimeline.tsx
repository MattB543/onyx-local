"use client";

import { CrmInteraction } from "@/app/app/crm/crmService";
import Button from "@/refresh-components/buttons/Button";
import { EmptyMessageCard } from "@opal/components";
import Text from "@/refresh-components/texts/Text";

import { SvgActivity, SvgPlusCircle } from "@opal/icons";

import TimelineInteractionCard from "./TimelineInteractionCard";

interface ActivityTimelineProps {
  interactions: CrmInteraction[];
  isLoading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  onLogInteraction: () => void;
  attendeeUserNameById?: Map<string, string>;
  attendeeContactNameById?: Map<string, string>;
  canDeleteInteractions?: boolean;
  onDeleteInteraction?: (interaction: CrmInteraction) => void;
}

export default function ActivityTimeline({
  interactions,
  isLoading,
  hasMore,
  onLoadMore,
  onLogInteraction,
  attendeeUserNameById,
  attendeeContactNameById,
  canDeleteInteractions = false,
  onDeleteInteraction,
}: ActivityTimelineProps) {
  return (
    <div className="flex flex-col gap-0">
      <div className="mb-4 flex items-center gap-2">
        <Text as="p" mainUiAction text05>
          Activity
        </Text>
        <Button
          action
          tertiary
          className="ml-auto"
          leftIcon={SvgPlusCircle}
          onClick={onLogInteraction}
        >
          Log Interaction
        </Button>
      </div>

      {isLoading ? (
        <Text as="p" secondaryBody text05 className="text-sm">
          Loading activity...
        </Text>
      ) : interactions.length === 0 ? (
        <EmptyMessageCard
          sizePreset="main-ui"
          icon={SvgActivity}
          title="No activity yet"
          description="Log your first interaction to start tracking activity."
        />
      ) : (
        <div>
          {interactions.map((interaction) => (
            <TimelineInteractionCard
              key={interaction.id}
              interaction={interaction}
              attendeeUserNameById={attendeeUserNameById}
              attendeeContactNameById={attendeeContactNameById}
              canDelete={canDeleteInteractions}
              onDelete={
                onDeleteInteraction
                  ? () => onDeleteInteraction(interaction)
                  : undefined
              }
            />
          ))}

          {hasMore && (
            <div className="mt-1 flex justify-center">
              <Button action tertiary onClick={onLoadMore}>
                Load more
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
