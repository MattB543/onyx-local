"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import Card from "@/refresh-components/cards/Card";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import ContactAvatar from "@/refresh-pages/crm/components/ContactAvatar";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import OrgAvatar from "@/refresh-pages/crm/components/OrgAvatar";
import StatusBadge from "@/refresh-pages/crm/components/StatusBadge";
import TypeBadge from "@/refresh-pages/crm/components/TypeBadge";
import CrmNav from "@/refresh-pages/crm/CrmNav";

import { SvgActivity, SvgOrganization, SvgUser } from "@opal/icons";

const RECENT_LIST_LIMIT = 5;
const INTERACTION_LOOKUP_LIMIT = 150;
const ORGANIZATION_LOOKUP_LIMIT = 150;

export default function CrmHomePage() {
  const [contactsSortBy, setContactsSortBy] = useState("updated_at");
  const [orgsSortBy, setOrgsSortBy] = useState("updated_at");

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
  const { organizations: organizationLookup } = useCrmOrganizations({
    pageNum: 0,
    pageSize: ORGANIZATION_LOOKUP_LIMIT,
  });
  const { interactions } = useCrmInteractions({
    pageNum: 0,
    pageSize: INTERACTION_LOOKUP_LIMIT,
  });

  const orgNameById = useMemo(() => {
    return new Map(
      organizationLookup.map((organization) => [
        organization.id,
        organization.name,
      ])
    );
  }, [organizationLookup]);

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="xl">
        <SettingsLayouts.Header
          icon={SvgUser}
          title="CRM"
          description="Manage your contacts, organizations, and interactions."
          titleIconInline
        >
          <CrmNav />
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
                    {interactions.length}
                  </Text>
                  <Text as="p" secondaryBody text03 className="text-sm">
                    Recent Interactions
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
                    onValueChange={setContactsSortBy}
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
                  const orgName = contact.organization_id
                    ? orgNameById.get(contact.organization_id) ||
                      "Linked organization"
                    : null;

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
                    onValueChange={setOrgsSortBy}
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
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </AppLayouts.Root>
  );
}
