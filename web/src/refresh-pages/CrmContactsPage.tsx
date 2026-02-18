"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { CrmContactStatus } from "@/app/app/crm/crmService";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { cn } from "@/lib/utils";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Pagination from "@/refresh-components/Pagination";
import Text from "@/refresh-components/texts/Text";
import ContactAvatar from "@/refresh-pages/crm/components/ContactAvatar";
import CreateContactModal from "@/refresh-pages/crm/components/CreateContactModal";
import StatusBadge from "@/refresh-pages/crm/components/StatusBadge";
import CrmNav from "@/refresh-pages/crm/CrmNav";

import { SvgPlusCircle, SvgTag, SvgUser } from "@opal/icons";

const PAGE_SIZE = 25;
const CONTACT_STATUSES: CrmContactStatus[] = [
  "lead",
  "active",
  "inactive",
  "archived",
];

function formatLabel(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function CrmContactsPage() {
  const searchParams = useSearchParams();
  const organizationIdFilter = searchParams.get("organization_id") ?? undefined;

  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState<CrmContactStatus | "all">(
    "all"
  );
  const [pageNum, setPageNum] = useState(0);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  const { contacts, totalItems, isLoading, error, refreshContacts } =
    useCrmContacts({
      q: searchText || undefined,
      status: statusFilter === "all" ? undefined : statusFilter,
      organizationId: organizationIdFilter,
      pageNum,
      pageSize: PAGE_SIZE,
    });

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(totalItems / PAGE_SIZE)),
    [totalItems]
  );

  const emptyDescription =
    searchText || statusFilter !== "all" || organizationIdFilter
      ? "Try adjusting filters or search terms."
      : "Create your first contact to get started.";

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgUser}
          title="CRM"
          description="Manage contacts and organizations."
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
              <Text as="p" secondaryBody text03>
                Showing contacts linked to the selected organization.
              </Text>
              <div className="flex justify-end">
                <Button action tertiary size="md" href="/app/crm/contacts">
                  Clear Filter
                </Button>
              </div>
            </Card>
          )}

          <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_220px_auto] md:items-center">
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
                setStatusFilter(value as CrmContactStatus | "all");
                setPageNum(0);
              }}
            >
              <InputSelect.Trigger placeholder="Filter by status" />
              <InputSelect.Content>
                <InputSelect.Item value="all">All statuses</InputSelect.Item>
                {CONTACT_STATUSES.map((status) => (
                  <InputSelect.Item key={status} value={status}>
                    {formatLabel(status)}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>

            <Text as="p" secondaryAction text03 className="md:justify-self-end">
              {totalItems} total
            </Text>
          </div>

          {error && (
            <Text as="p" secondaryBody className="text-status-error-03">
              Failed to load contacts.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03>
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
                const visibleTags = contact.tags.slice(0, 2);
                const remainingTagCount = Math.max(0, contact.tags.length - 2);
                const infoRow =
                  [contact.title, contact.location]
                    .filter(Boolean)
                    .join(" · ") || "No title or location";

                return (
                  <Link
                    key={contact.id}
                    href={`/app/crm/contacts/${contact.id}`}
                    className="block"
                  >
                    <Card
                      variant="secondary"
                      className="gap-2 transition-colors hover:bg-background-tint-02"
                    >
                      <div className="flex items-start gap-3">
                        <ContactAvatar
                          firstName={contact.first_name}
                          lastName={contact.last_name}
                        />

                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <Text as="p" mainUiAction text02>
                              {contact.full_name || contact.first_name}
                            </Text>
                            <StatusBadge status={contact.status} />
                          </div>

                          <Text as="p" secondaryBody text03>
                            {contact.email ||
                              contact.phone ||
                              "No contact info"}
                          </Text>

                          <Text as="p" secondaryBody text03>
                            {infoRow}
                          </Text>

                          {visibleTags.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {visibleTags.map((tag) => (
                                <span
                                  key={tag.id}
                                  className={cn(
                                    "inline-flex items-center gap-1 rounded-full bg-background-tint-02 px-2 py-0.5"
                                  )}
                                >
                                  <SvgTag
                                    size={10}
                                    className="stroke-text-03"
                                  />
                                  <Text as="span" figureSmallLabel text03>
                                    {tag.name}
                                  </Text>
                                </span>
                              ))}

                              {remainingTagCount > 0 && (
                                <span className="inline-flex items-center rounded-full bg-background-tint-02 px-2 py-0.5">
                                  <Text as="span" figureSmallLabel text03>
                                    +{remainingTagCount}
                                  </Text>
                                </span>
                              )}
                            </div>
                          )}
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
