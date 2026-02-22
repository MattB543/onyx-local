"use client";

import Link from "next/link";
import { useMemo } from "react";

import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import { cn } from "@/lib/utils";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import ContactAvatar from "@/refresh-pages/crm/components/ContactAvatar";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import OrgAvatar from "@/refresh-pages/crm/components/OrgAvatar";
import StatusBadge from "@/refresh-pages/crm/components/StatusBadge";
import TypeBadge from "@/refresh-pages/crm/components/TypeBadge";
import CrmNav from "@/refresh-pages/crm/CrmNav";

import { SvgActivity, SvgOrganization, SvgTag, SvgUser } from "@opal/icons";

const RECENT_LIST_LIMIT = 5;
const INTERACTION_LOOKUP_LIMIT = 150;
const ORGANIZATION_LOOKUP_LIMIT = 150;

interface LatestInteractionInfo {
  timestamp: string;
  title: string;
}

function toMs(value: string): number {
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

export default function CrmHomePage() {
  const {
    contacts,
    totalItems: totalContacts,
    isLoading: loadingContacts,
  } = useCrmContacts({ pageNum: 0, pageSize: RECENT_LIST_LIMIT });
  const {
    organizations,
    totalItems: totalOrgs,
    isLoading: loadingOrgs,
  } = useCrmOrganizations({ pageNum: 0, pageSize: RECENT_LIST_LIMIT });
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

  const latestInteractionByContactId = useMemo(() => {
    const latest = new Map<string, LatestInteractionInfo>();

    for (const interaction of interactions) {
      if (!interaction.contact_id) {
        continue;
      }

      const timestamp = interaction.occurred_at || interaction.created_at;
      const existing = latest.get(interaction.contact_id);

      if (!existing || toMs(timestamp) > toMs(existing.timestamp)) {
        latest.set(interaction.contact_id, {
          timestamp,
          title: interaction.title,
        });
      }
    }

    return latest;
  }, [interactions]);

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
            <div className="flex items-center justify-between">
              <Text as="p" mainUiAction text02>
                Recent Contacts
              </Text>
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
                  const latestInteraction = latestInteractionByContactId.get(
                    contact.id
                  );
                  const latestActivityDate = latestInteraction
                    ? formatRelativeDate(latestInteraction.timestamp)
                    : formatRelativeDate(contact.updated_at);
                  const titleLabel = contact.title || "No title";
                  const orgLabel = contact.organization_id
                    ? orgNameById.get(contact.organization_id) ||
                      "Linked organization"
                    : "No organization";
                  const visibleTags = contact.tags.slice(0, 2);
                  const remainingTags = Math.max(0, contact.tags.length - 2);

                  return (
                    <Link
                      key={contact.id}
                      href={`/app/crm/contacts/${contact.id}`}
                    >
                      <Card
                        variant="secondary"
                        className="gap-2 transition-colors hover:bg-background-tint-02"
                      >
                        <div className="flex items-start gap-3">
                          <ContactAvatar
                            firstName={contact.first_name}
                            lastName={contact.last_name}
                            size="sm"
                          />
                          <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <Text as="p" mainUiAction text02>
                                {contact.full_name || contact.first_name}
                              </Text>
                              <StatusBadge status={contact.status} />
                            </div>

                            <Text
                              as="p"
                              secondaryBody
                              text03
                              className="text-sm"
                            >
                              {titleLabel} · {orgLabel}
                            </Text>

                            <Text
                              as="p"
                              secondaryBody
                              text03
                              className="text-sm"
                            >
                              Latest activity:{" "}
                              <span className="font-medium text-text-04">
                                {latestActivityDate}
                              </span>
                              {latestInteraction && (
                                <>
                                  {" "}
                                  ·{" "}
                                  <span className="font-medium text-text-04">
                                    {latestInteraction.title}
                                  </span>
                                </>
                              )}
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
                                    <Text
                                      as="span"
                                      figureSmallLabel
                                      text02
                                      className="text-sm"
                                    >
                                      {tag.name}
                                    </Text>
                                  </span>
                                ))}
                                {remainingTags > 0 && (
                                  <span className="inline-flex items-center rounded-full bg-background-tint-02 px-2 py-0.5">
                                    <Text
                                      as="span"
                                      figureSmallLabel
                                      text02
                                      className="text-sm"
                                    >
                                      +{remainingTags}
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
          </div>

          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <Text as="p" mainUiAction text02>
                Recent Organizations
              </Text>
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
              <div className="flex flex-col gap-1.5">
                {organizations.map((organization) => (
                  <Link
                    key={organization.id}
                    href={`/app/crm/organizations/${organization.id}`}
                    className="flex items-center gap-3 rounded-lg p-2.5 transition-colors hover:bg-background-tint-02"
                  >
                    <OrgAvatar
                      name={organization.name}
                      type={organization.type}
                      size="sm"
                    />
                    <div className="min-w-0 flex-1">
                      <Text as="p" mainUiAction text02>
                        {organization.name}
                      </Text>
                      <Text as="p" secondaryBody text03 className="text-sm">
                        {[organization.sector, organization.location]
                          .filter(Boolean)
                          .join(" · ") || "No details"}
                      </Text>
                    </div>
                    <TypeBadge type={organization.type} />
                  </Link>
                ))}
              </div>
            )}
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </AppLayouts.Root>
  );
}
