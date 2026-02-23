"use client";

import { CrmInteraction } from "@/app/app/crm/crmService";
import Button from "@/refresh-components/buttons/Button";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import Text from "@/refresh-components/texts/Text";

import { SvgActivity, SvgPlusCircle } from "@opal/icons";

import { formatDateGroupLabel, getDateKey } from "./crmDateUtils";
import TimelineInteractionCard from "./TimelineInteractionCard";

interface DateGroup {
  dateKey: string;
  label: string;
  items: CrmInteraction[];
}

function groupInteractionsByDate(interactions: CrmInteraction[]): DateGroup[] {
  const groups = new Map<string, DateGroup>();

  for (const interaction of interactions) {
    const dateStr = interaction.occurred_at || interaction.created_at;
    const key = getDateKey(dateStr);
    if (!groups.has(key)) {
      groups.set(key, {
        dateKey: key,
        label: formatDateGroupLabel(dateStr),
        items: [],
      });
    }
    const group = groups.get(key);
    if (group) {
      group.items.push(interaction);
    }
  }

  return Array.from(groups.values());
}

interface ActivityTimelineProps {
  interactions: CrmInteraction[];
  isLoading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  onLogInteraction: () => void;
  attendeeUserNameById?: Map<string, string>;
  attendeeContactNameById?: Map<string, string>;
}

export default function ActivityTimeline({
  interactions,
  isLoading,
  hasMore,
  onLoadMore,
  onLogInteraction,
  attendeeUserNameById,
  attendeeContactNameById,
}: ActivityTimelineProps) {
  const grouped = groupInteractionsByDate(interactions);

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
        <EmptyMessage
          icon={SvgActivity}
          title="No activity yet"
          description="Log your first interaction to start tracking activity."
        />
      ) : (
        <div className="relative">
          <div className="bg-border-subtle absolute bottom-0 left-[15px] top-0 w-px" />

          {grouped.map((group) => (
            <div key={group.dateKey}>
              <div className="relative mb-3 flex items-center gap-3">
                <div className="relative z-10 flex w-[31px] justify-center">
                  <div className="h-2 w-2 rounded-full bg-border-02" />
                </div>
                <Text
                  as="p"
                  mainUiAction
                  text05
                  className="text-sm"
                >
                  {group.label}
                </Text>
              </div>

              {group.items.map((interaction) => (
                <TimelineInteractionCard
                  key={interaction.id}
                  interaction={interaction}
                  attendeeUserNameById={attendeeUserNameById}
                  attendeeContactNameById={attendeeContactNameById}
                />
              ))}
            </div>
          ))}

          {hasMore && (
            <div className="mt-4 flex justify-center">
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
