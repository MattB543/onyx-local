"use client";

import { useMemo, useState } from "react";

import {
  CrmEmailQueueEventStatus,
  CrmEmailQueueItem,
  CrmEmailQueueStatusFilter,
} from "@/app/app/crm/emailQueueService";
import { SettingsLayouts } from "@opal/layouts";
import {
  useCrmEmailQueue,
  useCrmEmailQueueConfigStatus,
} from "@/lib/hooks/useCrmEmailQueue";
import Card from "@/refresh-components/cards/Card";
import { EmptyMessageCard } from "@opal/components";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { PageSelector } from "@/components/PageSelector";
import Text from "@/refresh-components/texts/Text";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import CrmNav from "@/refresh-pages/crm/CrmNav";
import { cn } from "@/lib/utils";

import { SvgAlertTriangle, SvgMail } from "@opal/icons";

const PAGE_SIZE = 25;

type DisplayStatus = "pending" | "processing" | "processed" | "failed";

const STATUS_FILTER_OPTIONS: {
  value: CrmEmailQueueStatusFilter;
  label: string;
}[] = [
  { value: "pending", label: "Pending" },
  { value: "failed", label: "Failed" },
  { value: "processed", label: "Processed" },
];

function getDisplayStatus(status: CrmEmailQueueEventStatus): DisplayStatus {
  switch (status) {
    case "received":
      return "pending";
    case "enqueued":
      return "processing";
    case "failed":
      return "failed";
    case "consumed":
    case "dropped":
    default:
      return "processed";
  }
}

const STATUS_BADGE_CLASSES: Record<DisplayStatus, string> = {
  pending: "bg-status-warning-01 text-status-warning-05",
  processing: "bg-status-info-01 text-status-info-05",
  processed: "bg-status-success-01 text-status-success-05",
  failed: "bg-status-error-01 text-status-error-05",
};

const STATUS_BADGE_LABELS: Record<DisplayStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  processed: "Processed",
  failed: "Failed",
};

interface StatusBadgeProps {
  status: CrmEmailQueueEventStatus;
}

function StatusBadge({ status }: StatusBadgeProps) {
  const displayStatus = getDisplayStatus(status);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        STATUS_BADGE_CLASSES[displayStatus],
      )}
    >
      {STATUS_BADGE_LABELS[displayStatus]}
    </span>
  );
}

interface EmailQueueRowProps {
  event: CrmEmailQueueItem;
}

function EmailQueueRow({ event }: EmailQueueRowProps) {
  const [errorExpanded, setErrorExpanded] = useState(false);
  const receivedAt = event.event_time || event.created_at;

  return (
    <Card variant="secondary" className="[&>div]:items-stretch">
      <div className="flex w-full items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-background-tint-02">
          <SvgMail className="h-5 w-5 stroke-text-04" />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="truncate text-base font-semibold text-text-05">
            {event.from_email || "Unknown sender"}
          </span>
          <span className="truncate text-sm text-text-04">
            {event.subject || "(no subject)"}
          </span>
          {event.error_message && (
            <button
              type="button"
              className="text-left"
              title={event.error_message}
              onClick={() => setErrorExpanded((expanded) => !expanded)}
            >
              <span
                className={cn(
                  "block text-sm text-status-error-04",
                  !errorExpanded && "truncate",
                )}
              >
                {event.error_message}
              </span>
            </button>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <StatusBadge status={event.status} />
          <span className="text-sm text-text-03">
            {formatRelativeDate(receivedAt)}
          </span>
        </div>
      </div>
    </Card>
  );
}

export default function CrmEmailQueuePage() {
  const [statusFilter, setStatusFilter] = useState<
    CrmEmailQueueStatusFilter | "all"
  >("all");
  const [pageNum, setPageNum] = useState(0);

  const { configStatus, isLoading: configLoading } =
    useCrmEmailQueueConfigStatus();

  const notConfigured = !configLoading && configStatus?.configured === false;
  const envValueInvalid = notConfigured && configStatus?.env_value_set === true;
  const jobMissingOrDisabled =
    !configLoading &&
    configStatus?.configured === true &&
    (!configStatus.job_exists || !configStatus.job_enabled);

  const { events, totalItems, isLoading, error } = useCrmEmailQueue({
    status: statusFilter === "all" ? undefined : statusFilter,
    pageNum,
    pageSize: PAGE_SIZE,
  });

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(totalItems / PAGE_SIZE)),
    [totalItems],
  );

  const emptyDescription =
    statusFilter !== "all"
      ? "Try adjusting the status filter."
      : "Indexed emails will appear here as they enter the CRM pipeline.";

  return (
    <>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgMail}
          title="CRM"
          description="Manage contacts and organizations."
        >
          <CrmNav />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          {notConfigured ? (
            <Card variant="secondary">
              <div className="flex w-full items-start gap-3">
                <SvgAlertTriangle className="mt-0.5 h-5 w-5 shrink-0 stroke-status-warning-04" />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <Text as="p" mainUiAction text05>
                    Email-to-CRM is not configured
                  </Text>
                  <Text as="p" secondaryBody text03 className="text-sm">
                    {envValueInvalid
                      ? "The EMAIL_CRM_CUSTOM_JOB_ID environment variable is set but is not a valid UUID, so indexed emails do not emit CRM trigger events. Set it to the UUID of the email-to-CRM custom job and restart the indexing workers to enable this queue."
                      : "The EMAIL_CRM_CUSTOM_JOB_ID environment variable is not set, so indexed emails do not emit CRM trigger events. Set it to the UUID of the email-to-CRM custom job and restart the indexing workers to enable this queue."}
                  </Text>
                </div>
              </div>
            </Card>
          ) : (
            <>
              {jobMissingOrDisabled && (
                <Card variant="secondary">
                  <div className="flex w-full items-start gap-3">
                    <SvgAlertTriangle className="mt-0.5 h-5 w-5 shrink-0 stroke-status-warning-04" />
                    <Text as="p" secondaryBody text03 className="text-sm">
                      {configStatus && !configStatus.job_exists
                        ? "EMAIL_CRM_CUSTOM_JOB_ID is set, but no custom job with that ID exists. New emails will not be processed."
                        : "The email-to-CRM custom job is disabled. New emails will queue but will not be processed until it is re-enabled."}
                    </Text>
                  </div>
                </Card>
              )}

              <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_220px_auto] md:items-center">
                <div />

                <InputSelect
                  value={statusFilter}
                  onValueChange={(value) => {
                    setStatusFilter(value as CrmEmailQueueStatusFilter | "all");
                    setPageNum(0);
                  }}
                >
                  <InputSelect.Trigger placeholder="Filter by status" />
                  <InputSelect.Content>
                    <InputSelect.Item value="all">
                      All statuses
                    </InputSelect.Item>
                    {STATUS_FILTER_OPTIONS.map((option) => (
                      <InputSelect.Item key={option.value} value={option.value}>
                        {option.label}
                      </InputSelect.Item>
                    ))}
                  </InputSelect.Content>
                </InputSelect>

                <Text
                  as="p"
                  secondaryAction
                  text03
                  className="text-sm md:justify-self-end"
                >
                  {totalItems} total
                </Text>
              </div>

              {error && (
                <Text
                  as="p"
                  secondaryBody
                  className="text-sm text-status-error-03"
                >
                  Failed to load the email queue.
                </Text>
              )}

              {isLoading ? (
                <Text as="p" secondaryBody text03 className="text-sm">
                  Loading email queue...
                </Text>
              ) : events.length === 0 ? (
                <EmptyMessageCard
                  sizePreset="main-ui"
                  icon={SvgMail}
                  title="No emails found"
                  description={emptyDescription}
                />
              ) : (
                <div className="flex flex-col gap-2">
                  {events.map((event) => (
                    <EmailQueueRow key={event.id} event={event} />
                  ))}
                </div>
              )}

              {!isLoading && events.length > 0 && totalPages > 1 && (
                <PageSelector
                  currentPage={pageNum + 1}
                  totalPages={totalPages}
                  onPageChange={(nextPage) => setPageNum(nextPage - 1)}
                />
              )}
            </>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </>
  );
}
