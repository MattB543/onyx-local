"use client";

import { Route } from "next";
import Link from "next/link";
import { useCallback, useState } from "react";

import {
  exportCrmContacts,
  exportCrmInteractions,
  exportCrmOrganizations,
} from "@/app/app/crm/crmService";
import { SettingsLayouts } from "@opal/layouts";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import { useUser } from "@/providers/UserProvider";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Popover } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import ImportCsvModal from "@/views/crm/components/ImportCsvModal";
import ContactAvatar from "@/views/crm/components/ContactAvatar";
import InteractionTypeIcon from "@/views/crm/components/InteractionTypeIcon";
import { formatRelativeDate } from "@/views/crm/components/crmDateUtils";
import OrgAvatar from "@/views/crm/components/OrgAvatar";
import StatusBadge from "@/views/crm/components/StatusBadge";
import TypeBadge from "@/views/crm/components/TypeBadge";
import CrmNav from "@/views/crm/CrmNav";

import {
  SvgActivity,
  SvgDownload,
  SvgOrganization,
  SvgUploadCloud,
  SvgUser,
} from "@opal/icons";
import CopyEmailButton from "@/views/crm/components/CopyEmailButton";
import { Section } from "@/layouts/general-layouts";

const RECENT_LIST_LIMIT = 5;

export default function CrmHomePage() {
  const { isAdmin } = useUser();
  const [contactsSortBy, setContactsSortBy] = useState<
    "created_at" | "updated_at"
  >("updated_at");
  const [orgsSortBy, setOrgsSortBy] = useState<"created_at" | "updated_at">(
    "updated_at",
  );
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [exportPopoverOpen, setExportPopoverOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const handleExport = useCallback(async (exportFn: () => Promise<void>) => {
    setExporting(true);
    setExportPopoverOpen(false);
    try {
      await exportFn();
    } catch (err) {
      console.error("Failed to export:", err);
    } finally {
      setExporting(false);
    }
  }, []);

  const {
    contacts,
    totalItems: totalContacts,
    isLoading: loadingContacts,
  } = useCrmContacts({
    pageNum: 0,
    pageSize: RECENT_LIST_LIMIT,
    sortBy: contactsSortBy,
  });
  const {
    organizations,
    totalItems: totalOrgs,
    isLoading: loadingOrgs,
  } = useCrmOrganizations({
    pageNum: 0,
    pageSize: RECENT_LIST_LIMIT,
    sortBy: orgsSortBy,
  });
  const {
    interactions: recentInteractions,
    totalItems: totalInteractions,
    isLoading: loadingInteractions,
  } = useCrmInteractions({
    pageNum: 0,
    pageSize: RECENT_LIST_LIMIT,
  });

  return (
    <>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgUser}
          title="CRM"
          description="Manage your contacts, organizations, and interactions."
        >
          <CrmNav
            rightContent={
              <div className="flex items-center gap-2">
                <Popover
                  open={exportPopoverOpen}
                  onOpenChange={setExportPopoverOpen}
                >
                  <Popover.Trigger asChild>
                    <Button
                      secondary
                      leftIcon={SvgDownload}
                      disabled={exporting}
                    >
                      {exporting ? "Exporting..." : "Export"}
                    </Button>
                  </Popover.Trigger>
                  <Popover.Content align="end">
                    <Section gap={0.5} alignItems="stretch">
                      <Button
                        tertiary
                        size="md"
                        className="!w-full justify-start"
                        onClick={() => handleExport(exportCrmContacts)}
                      >
                        Export Contacts
                      </Button>
                      <Button
                        tertiary
                        size="md"
                        className="!w-full justify-start"
                        onClick={() => handleExport(exportCrmOrganizations)}
                      >
                        Export Organizations
                      </Button>
                      <Button
                        tertiary
                        size="md"
                        className="!w-full justify-start"
                        onClick={() => handleExport(exportCrmInteractions)}
                      >
                        Export Interactions
                      </Button>
                    </Section>
                  </Popover.Content>
                </Popover>
                {isAdmin && (
                  <Button
                    secondary
                    leftIcon={SvgUploadCloud}
                    onClick={() => setImportModalOpen(true)}
                  >
                    Import
                  </Button>
                )}
              </div>
            }
          />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Link href="/app/crm/contacts">
              <Card
                variant="secondary"
                className="cursor-pointer transition-colors hover:bg-background-tint-02"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-background-tint-02">
                    <SvgUser size={20} className="stroke-text-04" />
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <Text as="p" headingH3>
                      {loadingContacts ? "--" : totalContacts}
                    </Text>
                    <Text as="p" secondaryBody text03 className="text-sm">
                      Contacts
                    </Text>
                  </div>
                </div>
              </Card>
            </Link>

            <Link href="/app/crm/organizations">
              <Card
                variant="secondary"
                className="cursor-pointer transition-colors hover:bg-background-tint-02"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-background-tint-02">
                    <SvgOrganization size={20} className="stroke-text-04" />
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <Text as="p" headingH3>
                      {loadingOrgs ? "--" : totalOrgs}
                    </Text>
                    <Text as="p" secondaryBody text03 className="text-sm">
                      Organizations
                    </Text>
                  </div>
                </div>
              </Card>
            </Link>

            <Card variant="secondary">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-background-tint-02">
                  <SvgActivity size={20} className="stroke-text-04" />
                </div>
                <div className="flex flex-col gap-0.5">
                  <Text as="p" headingH3>
                    {loadingInteractions ? "--" : totalInteractions}
                  </Text>
                  <Text as="p" secondaryBody text03 className="text-sm">
                    Interactions
                  </Text>
                </div>
              </div>
            </Card>
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <Text as="p" mainUiAction text02>
                Recent Contacts
              </Text>
              <div className="flex items-center gap-2">
                <div className="w-[160px]">
                  <InputSelect
                    value={contactsSortBy}
                    onValueChange={(v) =>
                      setContactsSortBy(v as "created_at" | "updated_at")
                    }
                  >
                    <InputSelect.Trigger placeholder="Sort by" />
                    <InputSelect.Content>
                      <InputSelect.Item value="updated_at">
                        Updated date
                      </InputSelect.Item>
                      <InputSelect.Item value="created_at">
                        Created date
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
                <Link href="/app/crm/contacts">
                  <Text
                    as="span"
                    secondaryBody
                    className="text-sm text-text-04 hover:underline"
                  >
                    View all
                  </Text>
                </Link>
              </div>
            </div>

            {loadingContacts ? (
              <Text as="p" secondaryBody text03 className="text-sm">
                Loading...
              </Text>
            ) : contacts.length === 0 ? (
              <Card variant="tertiary">
                <Text as="p" secondaryBody text03 className="text-sm">
                  No contacts yet. Create your first contact to get started.
                </Text>
              </Card>
            ) : (
              <div className="flex flex-col gap-2">
                {contacts.map((contact) => {
                  return (
                    <Link
                      key={contact.id}
                      href={`/app/crm/contacts/${contact.id}`}
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
                              profilePictureUrl={contact.profile_picture_url}
                            />
                          </div>
                          <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <span className="text-base font-semibold text-text-05">
                              {contact.full_name || contact.email || "Contact"}
                            </span>
                            {contact.email ? (
                              <div className="flex items-center gap-1">
                                <span className="truncate text-sm text-text-04">
                                  {contact.email}
                                </span>
                                <CopyEmailButton email={contact.email!} />
                              </div>
                            ) : (
                              <span className="text-sm text-text-03">
                                No email
                              </span>
                            )}
                            <span className="truncate text-sm text-text-03">
                              {contact.title
                                ? contact.organization_name
                                  ? `${contact.title} at ${contact.organization_name}`
                                  : contact.title
                                : contact.organization_name
                                  ? `at ${contact.organization_name}`
                                  : "No title"}
                            </span>
                          </div>
                          <div className="flex shrink-0 flex-col items-end gap-1">
                            <StatusBadge status={contact.status} />
                            <div className="flex flex-col items-end gap-0.5 text-sm text-text-03">
                              <span>
                                Created {formatRelativeDate(contact.created_at)}
                              </span>
                              <span>
                                Updated {formatRelativeDate(contact.updated_at)}
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
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <Text as="p" mainUiAction text02>
                Recent Organizations
              </Text>
              <div className="flex items-center gap-2">
                <div className="w-[160px]">
                  <InputSelect
                    value={orgsSortBy}
                    onValueChange={(v) =>
                      setOrgsSortBy(v as "created_at" | "updated_at")
                    }
                  >
                    <InputSelect.Trigger placeholder="Sort by" />
                    <InputSelect.Content>
                      <InputSelect.Item value="updated_at">
                        Updated date
                      </InputSelect.Item>
                      <InputSelect.Item value="created_at">
                        Created date
                      </InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelect>
                </div>
                <Link href="/app/crm/organizations">
                  <Text
                    as="span"
                    secondaryBody
                    className="text-sm text-text-04 hover:underline"
                  >
                    View all
                  </Text>
                </Link>
              </div>
            </div>

            {loadingOrgs ? (
              <Text as="p" secondaryBody text03 className="text-sm">
                Loading...
              </Text>
            ) : organizations.length === 0 ? (
              <Card variant="tertiary">
                <Text as="p" secondaryBody text03 className="text-sm">
                  No organizations yet. Create your first organization to get
                  started.
                </Text>
              </Card>
            ) : (
              <div className="flex flex-col gap-2">
                {organizations.map((organization) => {
                  const websiteDisplay = organization.website
                    ? organization.website.replace(/^https?:\/\//i, "")
                    : "No website";

                  return (
                    <Link
                      key={organization.id}
                      href={`/app/crm/organizations/${organization.id}`}
                    >
                      <Card
                        variant="secondary"
                        className="[&>div]:items-stretch transition-colors hover:bg-background-tint-02"
                      >
                        <div className="flex w-full items-start gap-3">
                          <OrgAvatar
                            name={organization.name}
                            type={organization.type}
                            size="lg"
                          />
                          <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <span className="text-base font-semibold text-text-05">
                              {organization.name}
                            </span>
                            {organization.website ? (
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.preventDefault();
                                  event.stopPropagation();
                                  const href = organization.website!.startsWith(
                                    "http",
                                  )
                                    ? organization.website!
                                    : `https://${organization.website!}`;
                                  window.open(
                                    href,
                                    "_blank",
                                    "noopener,noreferrer",
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
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <Text as="p" mainUiAction text02>
                Recent Interactions
              </Text>
            </div>

            {loadingInteractions ? (
              <Text as="p" secondaryBody text03 className="text-sm">
                Loading...
              </Text>
            ) : recentInteractions.length === 0 ? (
              <Card variant="tertiary">
                <Text as="p" secondaryBody text03 className="text-sm">
                  No interactions yet. Log your first interaction to get
                  started.
                </Text>
              </Card>
            ) : (
              <div className="flex flex-col gap-2">
                {recentInteractions.map((interaction) => {
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
                            <span className="line-clamp-1 text-sm text-text-03">
                              {interaction.summary}
                            </span>
                          )}
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <div className="flex flex-col items-end gap-0.5 text-sm text-text-03">
                            <span>
                              {formatRelativeDate(
                                interaction.occurred_at ||
                                  interaction.created_at,
                              )}
                            </span>
                          </div>
                        </div>
                      </div>
                    </Card>
                  );

                  return linkHref ? (
                    <Link key={interaction.id} href={linkHref as Route}>
                      {card}
                    </Link>
                  ) : (
                    <div key={interaction.id}>{card}</div>
                  );
                })}
              </div>
            )}
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <ImportCsvModal
        open={importModalOpen}
        onOpenChange={setImportModalOpen}
        onSuccess={() => {
          // SWR cache is invalidated inside the modal
        }}
      />
    </>
  );
}
