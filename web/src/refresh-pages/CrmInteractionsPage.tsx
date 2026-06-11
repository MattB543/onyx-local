"use client";

import { Route } from "next";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import {
  CrmInteractionType,
  exportCrmInteractions,
} from "@/app/app/crm/crmService";
import useShareableUsers from "@/hooks/useShareableUsers";
import * as AppLayouts from "@/layouts/app-layouts";
import { SettingsLayouts } from "@opal/layouts";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import { useUser } from "@/providers/UserProvider";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import { EmptyMessageCard } from "@opal/components";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { PageSelector } from "@/components/PageSelector";
import Text from "@/refresh-components/texts/Text";
import InteractionTypeIcon from "@/refresh-pages/crm/components/InteractionTypeIcon";
import ImportCsvModal from "@/refresh-pages/crm/components/ImportCsvModal";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import CrmNav from "@/refresh-pages/crm/CrmNav";
import { formatCrmLabel } from "@/refresh-pages/crm/crmOptions";

import {
  SvgActivity,
  SvgDownload,
  SvgMoreHorizontal,
  SvgUploadCloud,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { Popover } from "@opal/components";

const PAGE_SIZE = 25;

const INTERACTION_TYPE_OPTIONS: CrmInteractionType[] = [
  "note",
  "call",
  "email",
  "meeting",
  "event",
];

export default function CrmInteractionsPage() {
  const { user, isAdmin } = useUser();
  const { data: usersData } = useShareableUsers({ includeApiKeys: false });
  const [typeFilter, setTypeFilter] = useState<CrmInteractionType | "all">(
    "all"
  );
  const [ownerFilter, setOwnerFilter] = useState<string>("all");
  const [pageNum, setPageNum] = useState(0);
  const [morePopoverOpen, setMorePopoverOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      await exportCrmInteractions();
    } catch (err) {
      console.error("Failed to export interactions:", err);
    } finally {
      setExporting(false);
    }
  }, []);

  const ownerOptions = useMemo(
    () =>
      (usersData || [])
        .filter((candidate) => candidate.id !== user?.id)
        .map((candidate) => ({
          value: candidate.id,
          label: candidate.email,
        })),
    [usersData, user?.id]
  );
  const ownerFilterId =
    ownerFilter === "all"
      ? undefined
      : ownerFilter === "me"
        ? user?.id
        : ownerFilter;

  const { interactions, totalItems, isLoading, error } = useCrmInteractions({
    pageNum,
    pageSize: PAGE_SIZE,
    interactionType: typeFilter === "all" ? undefined : typeFilter,
    loggedBy: ownerFilterId,
  });

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(totalItems / PAGE_SIZE)),
    [totalItems]
  );

  const emptyDescription =
    typeFilter !== "all" || ownerFilter !== "all"
      ? "Try adjusting filters."
      : "Log your first interaction to get started.";

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgActivity}
          title="CRM"
          description="Manage contacts and organizations."
        >
          <CrmNav
            rightContent={
              <div className="flex items-center gap-2">
                <Popover
                  open={morePopoverOpen}
                  onOpenChange={setMorePopoverOpen}
                >
                  <Popover.Trigger asChild>
                    <Button secondary className="!p-2">
                      <SvgMoreHorizontal className="h-4 w-4 rotate-90 stroke-text-03" />
                    </Button>
                  </Popover.Trigger>
                  <Popover.Content align="end">
                    <Section gap={0.5} alignItems="stretch">
                      <Button
                        tertiary
                        size="md"
                        leftIcon={SvgDownload}
                        className="gap-2"
                        onClick={() => {
                          setMorePopoverOpen(false);
                          handleExport();
                        }}
                        disabled={exporting}
                      >
                        {exporting ? "Exporting..." : "Export Interactions"}
                      </Button>
                      {isAdmin && (
                        <Button
                          tertiary
                          size="md"
                          leftIcon={SvgUploadCloud}
                          className="gap-2"
                          onClick={() => {
                            setMorePopoverOpen(false);
                            setImportModalOpen(true);
                          }}
                        >
                          Import CSV
                        </Button>
                      )}
                    </Section>
                  </Popover.Content>
                </Popover>
              </div>
            }
          />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_220px_220px_auto] md:items-center">
            <div />

            <InputSelect
              value={typeFilter}
              onValueChange={(value) => {
                setTypeFilter(value as CrmInteractionType | "all");
                setPageNum(0);
              }}
            >
              <InputSelect.Trigger placeholder="Filter by type" />
              <InputSelect.Content>
                <InputSelect.Item value="all">All types</InputSelect.Item>
                {INTERACTION_TYPE_OPTIONS.map((type) => (
                  <InputSelect.Item key={type} value={type}>
                    {formatCrmLabel(type)}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>

            <InputSelect
              value={ownerFilter}
              onValueChange={(value) => {
                setOwnerFilter(value);
                setPageNum(0);
              }}
            >
              <InputSelect.Trigger placeholder="Filter by owner" />
              <InputSelect.Content>
                <InputSelect.Item value="all">All owners</InputSelect.Item>
                <InputSelect.Item value="me">Me</InputSelect.Item>
                {ownerOptions.map((owner) => (
                  <InputSelect.Item key={owner.value} value={owner.value}>
                    {owner.label}
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
            <Text as="p" secondaryBody className="text-sm text-status-error-03">
              Failed to load interactions.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03 className="text-sm">
              Loading interactions...
            </Text>
          ) : interactions.length === 0 ? (
            <EmptyMessageCard
              sizePreset="main-ui"
              icon={SvgActivity}
              title="No interactions found"
              description={emptyDescription}
            />
          ) : (
            <div className="flex flex-col gap-2">
              {interactions.map((interaction) => {
                const linkHref = interaction.contact_id
                  ? `/app/crm/contacts/${interaction.contact_id}`
                  : interaction.organization_id
                    ? `/app/crm/organizations/${interaction.organization_id}`
                    : null;

                const card = (
                  <Card
                    variant="secondary"
                    className="[&>div]:items-stretch transition-colors hover:bg-background-tint-02"
                  >
                    <div className="flex w-full items-start gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-background-tint-02">
                        <InteractionTypeIcon
                          type={interaction.type}
                          size={20}
                          className="stroke-text-04"
                        />
                      </div>
                      <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <span className="truncate text-base font-semibold text-text-05">
                          {[
                            interaction.type.charAt(0).toUpperCase() +
                              interaction.type.slice(1),
                            interaction.contact_name,
                            interaction.organization_name
                              ? `at ${interaction.organization_name}`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" \u00B7 ")}
                        </span>
                        <span className="truncate text-sm text-text-04">
                          {interaction.title}
                        </span>
                        {interaction.summary && (
                          <span className="line-clamp-2 text-sm text-text-03">
                            {interaction.summary}
                          </span>
                        )}
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <div className="flex flex-col items-end gap-0.5 text-sm text-text-03">
                          <span>
                            {formatRelativeDate(
                              interaction.occurred_at || interaction.created_at
                            )}
                          </span>
                        </div>
                      </div>
                    </div>
                  </Card>
                );

                return linkHref ? (
                  <Link
                    key={interaction.id}
                    href={linkHref as Route}
                    className="block"
                  >
                    {card}
                  </Link>
                ) : (
                  <div key={interaction.id}>{card}</div>
                );
              })}
            </div>
          )}

          {!isLoading && interactions.length > 0 && totalPages > 1 && (
            <PageSelector
              currentPage={pageNum + 1}
              totalPages={totalPages}
              onPageChange={(nextPage) => setPageNum(nextPage - 1)}
            />
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <ImportCsvModal
        open={importModalOpen}
        onOpenChange={setImportModalOpen}
        defaultEntityType="interactions"
        onSuccess={() => {
          setPageNum(0);
        }}
      />
    </AppLayouts.Root>
  );
}
