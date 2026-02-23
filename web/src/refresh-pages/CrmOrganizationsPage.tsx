"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { CrmOrganizationType } from "@/app/app/crm/crmService";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Pagination from "@/refresh-components/Pagination";
import Text from "@/refresh-components/texts/Text";
import CreateOrganizationModal from "@/refresh-pages/crm/components/CreateOrganizationModal";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import OrgAvatar from "@/refresh-pages/crm/components/OrgAvatar";
import TypeBadge from "@/refresh-pages/crm/components/TypeBadge";
import CrmNav from "@/refresh-pages/crm/CrmNav";
import {
  formatCrmLabel,
  ORGANIZATION_TYPE_OPTIONS,
} from "@/refresh-pages/crm/crmOptions";

import { SvgOrganization, SvgPlusCircle } from "@opal/icons";

const PAGE_SIZE = 25;

export default function CrmOrganizationsPage() {
  const [searchText, setSearchText] = useState("");
  const [typeFilter, setTypeFilter] = useState<CrmOrganizationType | "all">(
    "all"
  );
  const [pageNum, setPageNum] = useState(0);
  const [createModalOpen, setCreateModalOpen] = useState(false);

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
      <SettingsLayouts.Root width="xl">
        <SettingsLayouts.Header
          icon={SvgOrganization}
          title="CRM"
          description="Manage contacts and organizations."
          titleIconInline
        >
          <CrmNav
            rightContent={
              <Button
                action
                primary
                leftIcon={SvgPlusCircle}
                onClick={() => setCreateModalOpen(true)}
              >
                New Organization
              </Button>
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
                                const href = organization.website!.startsWith("http")
                                  ? organization.website!
                                  : `https://${organization.website!}`;
                                window.open(href, "_blank", "noopener,noreferrer");
                              }}
                              className="truncate text-left text-sm text-text-04 hover:underline"
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
            <Pagination
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
    </AppLayouts.Root>
  );
}
