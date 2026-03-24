"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import {
  CrmOrganizationType,
  exportCrmOrganizations,
} from "@/app/app/crm/crmService";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import { useUser } from "@/providers/UserProvider";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { PageSelector } from "@/components/PageSelector";
import Text from "@/refresh-components/texts/Text";
import CreateOrganizationModal from "@/refresh-pages/crm/components/CreateOrganizationModal";
import ImportCsvModal from "@/refresh-pages/crm/components/ImportCsvModal";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import OrgAvatar from "@/refresh-pages/crm/components/OrgAvatar";
import TypeBadge from "@/refresh-pages/crm/components/TypeBadge";
import CrmNav from "@/refresh-pages/crm/CrmNav";
import {
  formatCrmLabel,
  ORGANIZATION_TYPE_OPTIONS,
} from "@/refresh-pages/crm/crmOptions";

import {
  SvgDownload,
  SvgMoreHorizontal,
  SvgOrganization,
  SvgPlusCircle,
  SvgUploadCloud,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import Popover from "@/refresh-components/Popover";

const PAGE_SIZE = 25;

export default function CrmOrganizationsPage() {
  const { isAdmin } = useUser();
  const [searchText, setSearchText] = useState("");
  const [typeFilter, setTypeFilter] = useState<CrmOrganizationType | "all">(
    "all"
  );
  const [pageNum, setPageNum] = useState(0);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [morePopoverOpen, setMorePopoverOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      await exportCrmOrganizations();
    } catch (err) {
      console.error("Failed to export organizations:", err);
    } finally {
      setExporting(false);
    }
  }, []);

  const { organizations, totalItems, isLoading, error, refreshOrganizations } =
    useCrmOrganizations({
      q: searchText || undefined,
      type: typeFilter === "all" ? undefined : typeFilter,
      pageNum,
      pageSize: PAGE_SIZE,
    });

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(totalItems / PAGE_SIZE)),
    [totalItems]
  );

  const emptyDescription =
    searchText || typeFilter !== "all"
      ? "Try adjusting filters or search terms."
      : "Create your first organization to get started.";

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgOrganization}
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
                        {exporting ? "Exporting..." : "Export Organizations"}
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
                <Button
                  action
                  primary
                  leftIcon={SvgPlusCircle}
                  onClick={() => setCreateModalOpen(true)}
                >
                  New Organization
                </Button>
              </div>
            }
          />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_220px_auto] md:items-center">
            <InputTypeIn
              value={searchText}
              onChange={(event) => {
                setSearchText(event.target.value);
                setPageNum(0);
              }}
              placeholder="Search organizations"
              leftSearchIcon
            />

            <InputSelect
              value={typeFilter}
              onValueChange={(value) => {
                setTypeFilter(value as CrmOrganizationType | "all");
                setPageNum(0);
              }}
            >
              <InputSelect.Trigger placeholder="Filter by type" />
              <InputSelect.Content>
                <InputSelect.Item value="all">All types</InputSelect.Item>
                {ORGANIZATION_TYPE_OPTIONS.map((type) => (
                  <InputSelect.Item key={type} value={type}>
                    {formatCrmLabel(type)}
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
              Failed to load organizations.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03 className="text-sm">
              Loading organizations...
            </Text>
          ) : organizations.length === 0 ? (
            <EmptyMessage
              icon={SvgOrganization}
              title="No organizations found"
              description={emptyDescription}
            />
          ) : (
            <div className="flex flex-col gap-2">
              {organizations.map((organization) => {
                const websiteDisplay = organization.website
                  ? organization.website.replace(/^https?:\/\//i, "")
                  : null;

                return (
                  <Link
                    key={organization.id}
                    href={`/app/crm/organizations/${organization.id}`}
                    className="block"
                  >
                    <Card
                      variant="secondary"
                      className="[&>div]:items-stretch transition-colors hover:bg-background-tint-02"
                    >
                      <div className="flex w-full items-center gap-3">
                        <OrgAvatar
                          name={organization.name}
                          type={organization.type}
                          size="lg"
                        />
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                          <span className="text-base font-semibold text-text-05">
                            {organization.name}
                          </span>
                          {websiteDisplay ? (
                            <button
                              type="button"
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                const href = organization.website!.startsWith(
                                  "http"
                                )
                                  ? organization.website!
                                  : `https://${organization.website!}`;
                                window.open(
                                  href,
                                  "_blank",
                                  "noopener,noreferrer"
                                );
                              }}
                              className="w-fit max-w-full truncate text-left text-sm text-text-04 hover:underline"
                            >
                              {websiteDisplay}
                            </button>
                          ) : (
                            <span className="text-sm text-text-03">
                              No website
                            </span>
                          )}
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <TypeBadge type={organization.type} />
                          <div className="flex flex-col items-end gap-0.5 text-sm text-text-03">
                            <span>
                              Created{" "}
                              {formatRelativeDate(organization.created_at)}
                            </span>
                            <span>
                              Updated{" "}
                              {formatRelativeDate(organization.updated_at)}
                            </span>
                          </div>
                        </div>
                      </div>
                    </Card>
                  </Link>
                );
              })}
            </div>
          )}

          {!isLoading && organizations.length > 0 && totalPages > 1 && (
            <PageSelector
              currentPage={pageNum + 1}
              totalPages={totalPages}
              onPageChange={(nextPage) => setPageNum(nextPage - 1)}
            />
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <CreateOrganizationModal
        open={createModalOpen}
        onOpenChange={setCreateModalOpen}
        onSuccess={() => {
          setPageNum(0);
          void refreshOrganizations();
        }}
      />

      <ImportCsvModal
        open={importModalOpen}
        onOpenChange={setImportModalOpen}
        defaultEntityType="organizations"
        onSuccess={() => {
          setPageNum(0);
          void refreshOrganizations();
        }}
      />
    </AppLayouts.Root>
  );
}
