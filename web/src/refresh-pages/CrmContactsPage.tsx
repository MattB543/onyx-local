"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { CrmContactStage } from "@/app/app/crm/crmService";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import { useCrmSettings } from "@/lib/hooks/useCrmSettings";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import type { ComboBoxOption } from "@/refresh-components/inputs/InputComboBox";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Pagination from "@/refresh-components/Pagination";
import Text from "@/refresh-components/texts/Text";
import ContactAvatar from "@/refresh-pages/crm/components/ContactAvatar";
import CreateContactModal from "@/refresh-pages/crm/components/CreateContactModal";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import StatusBadge from "@/refresh-pages/crm/components/StatusBadge";
import CrmNav from "@/refresh-pages/crm/CrmNav";
import {
  DEFAULT_CRM_CATEGORY_SUGGESTIONS,
  DEFAULT_CRM_STAGE_OPTIONS,
  formatCrmLabel,
} from "@/refresh-pages/crm/crmOptions";

import { SvgPlusCircle, SvgUser } from "@opal/icons";

const PAGE_SIZE = 25;

export default function CrmContactsPage() {
  const searchParams = useSearchParams();
  const organizationIdFilter = searchParams.get("organization_id") ?? undefined;
  const { crmSettings } = useCrmSettings();
  const stageOptions = useMemo(
    () =>
      crmSettings?.contact_stage_options?.length
        ? crmSettings.contact_stage_options
        : DEFAULT_CRM_STAGE_OPTIONS,
    [crmSettings?.contact_stage_options]
  );
  const categoryOptions = useMemo(
    () =>
      crmSettings?.contact_category_suggestions?.length
        ? crmSettings.contact_category_suggestions
        : DEFAULT_CRM_CATEGORY_SUGGESTIONS,
    [crmSettings?.contact_category_suggestions]
  );

  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState<CrmContactStage | "all">(
    "all"
  );
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [orgFilterText, setOrgFilterText] = useState("");
  const [orgFilterId, setOrgFilterId] = useState<string | undefined>(undefined);
  const [pageNum, setPageNum] = useState(0);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  const { organizations: orgLookup } = useCrmOrganizations({
    pageNum: 0,
    pageSize: 150,
  });
  const orgNameById = useMemo(
    () => new Map(orgLookup.map((o) => [o.id, o.name])),
    [orgLookup]
  );
  const orgOptions = useMemo<ComboBoxOption[]>(
    () => orgLookup.map((o) => ({ value: o.id, label: o.name })),
    [orgLookup]
  );

  const { contacts, totalItems, isLoading, error, refreshContacts } =
    useCrmContacts({
      q: searchText || undefined,
      status: statusFilter === "all" ? undefined : statusFilter,
      category: categoryFilter === "all" ? undefined : categoryFilter,
      organizationId: organizationIdFilter ?? orgFilterId,
      pageNum,
      pageSize: PAGE_SIZE,
    });

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(totalItems / PAGE_SIZE)),
    [totalItems]
  );

  const emptyDescription =
    searchText ||
    statusFilter !== "all" ||
    categoryFilter !== "all" ||
    orgFilterId ||
    organizationIdFilter
      ? "Try adjusting filters or search terms."
      : "Create your first contact to get started.";

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="xl">
        <SettingsLayouts.Header
          icon={SvgUser}
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
                New Contact
              </Button>
            }
          />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          {organizationIdFilter && (
            <Card variant="secondary" className="gap-2">
              <Text as="p" secondaryBody text03 className="text-sm">
                Showing contacts linked to the selected organization.
              </Text>
              <div className="flex justify-end">
                <Button action tertiary size="md" href="/app/crm/contacts">
                  Clear Filter
                </Button>
              </div>
            </Card>
          )}

          <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_180px_180px_180px_auto] md:items-center">
            <InputTypeIn
              value={searchText}
              onChange={(event) => {
                setSearchText(event.target.value);
                setPageNum(0);
              }}
              placeholder="Search contacts"
              leftSearchIcon
            />

            <InputSelect
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value as CrmContactStage | "all");
                setPageNum(0);
              }}
            >
              <InputSelect.Trigger placeholder="Filter by status" />
              <InputSelect.Content>
                <InputSelect.Item value="all">All statuses</InputSelect.Item>
                {stageOptions.map((status) => (
                  <InputSelect.Item key={status} value={status}>
                    {formatCrmLabel(status)}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>

            <InputSelect
              value={categoryFilter}
              onValueChange={(value) => {
                setCategoryFilter(value);
                setPageNum(0);
              }}
            >
              <InputSelect.Trigger placeholder="Filter by category" />
              <InputSelect.Content>
                <InputSelect.Item value="all">
                  All categories
                </InputSelect.Item>
                {categoryOptions.map((category) => (
                  <InputSelect.Item key={category} value={category}>
                    {formatCrmLabel(category)}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>

            <InputComboBox
              value={orgFilterText}
              onChange={(e) => {
                setOrgFilterText(e.target.value);
                if (!e.target.value) {
                  setOrgFilterId(undefined);
                  setPageNum(0);
                }
              }}
              onValueChange={(value) => {
                setOrgFilterId(value);
                setOrgFilterText(orgNameById.get(value) ?? "");
                setPageNum(0);
              }}
              onClear={() => {
                setOrgFilterId(undefined);
                setOrgFilterText("");
                setPageNum(0);
              }}
              options={orgOptions}
              placeholder="Filter by org"
              strict
              leftSearchIcon
              isError={false}
              disabled={!!organizationIdFilter}
            />

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
              Failed to load contacts.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03 className="text-sm">
              Loading contacts...
            </Text>
          ) : contacts.length === 0 ? (
            <EmptyMessage
              icon={SvgUser}
              title="No contacts found"
              description={emptyDescription}
            />
          ) : (
            <div className="flex flex-col gap-2">
              {contacts.map((contact) => {
                const orgName = contact.organization_id
                  ? orgNameById.get(contact.organization_id) ||
                    "Linked organization"
                  : null;

                return (
                  <Link
                    key={contact.id}
                    href={`/app/crm/contacts/${contact.id}`}
                    className="block"
                  >
                    <Card
                      variant="secondary"
                      className="[&>div]:items-stretch transition-colors hover:bg-background-tint-02"
                    >
                      <div className="flex w-full items-start gap-3">
                        <div className="self-center">
                          <ContactAvatar
                            firstName={contact.first_name}
                            lastName={contact.last_name}
                            size="lg"
                          />
                        </div>
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                          <span className="text-base font-semibold text-text-05">
                            {contact.full_name || contact.first_name}
                          </span>
                          <span className="text-sm text-text-03">
                            {contact.title || "No title"}
                          </span>
                          <span className="truncate text-sm text-text-03">
                            {orgName || "No organization"}
                          </span>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <StatusBadge status={contact.status} />
                          <div className="flex flex-col items-end gap-0.5 text-sm text-text-03">
                            <span>
                              Created{" "}
                              {formatRelativeDate(contact.created_at)}
                            </span>
                            <span>
                              Updated{" "}
                              {formatRelativeDate(contact.updated_at)}
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

          {!isLoading && contacts.length > 0 && totalPages > 1 && (
            <Pagination
              currentPage={pageNum + 1}
              totalPages={totalPages}
              onPageChange={(nextPage) => setPageNum(nextPage - 1)}
            />
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <CreateContactModal
        open={createModalOpen}
        onOpenChange={setCreateModalOpen}
        organizationId={organizationIdFilter}
        onSuccess={() => {
          setPageNum(0);
          void refreshContacts();
        }}
      />
    </AppLayouts.Root>
  );
}
