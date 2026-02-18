"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import { cn } from "@/lib/utils";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Pagination from "@/refresh-components/Pagination";
import Text from "@/refresh-components/texts/Text";
import CreateOrganizationModal from "@/refresh-pages/crm/components/CreateOrganizationModal";
import OrgAvatar from "@/refresh-pages/crm/components/OrgAvatar";
import TypeBadge from "@/refresh-pages/crm/components/TypeBadge";
import CrmNav from "@/refresh-pages/crm/CrmNav";

import { SvgGlobe, SvgOrganization, SvgPlusCircle, SvgTag } from "@opal/icons";

const PAGE_SIZE = 25;

function websiteLabel(website: string | null): string {
  if (!website) {
    return "No website";
  }

  return website.replace(/^https?:\/\//i, "");
}

export default function CrmOrganizationsPage() {
  const [searchText, setSearchText] = useState("");
  const [pageNum, setPageNum] = useState(0);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  const { organizations, totalItems, isLoading, error, refreshOrganizations } =
    useCrmOrganizations({
      q: searchText || undefined,
      pageNum,
      pageSize: PAGE_SIZE,
    });

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(totalItems / PAGE_SIZE)),
    [totalItems]
  );

  const emptyDescription = searchText
    ? "Try a broader search query."
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
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
            <InputTypeIn
              value={searchText}
              onChange={(event) => {
                setSearchText(event.target.value);
                setPageNum(0);
              }}
              placeholder="Search organizations"
              leftSearchIcon
            />

            <Text as="p" secondaryAction text03 className="md:justify-self-end">
              {totalItems} total
            </Text>
          </div>

          {error && (
            <Text as="p" secondaryBody className="text-status-error-03">
              Failed to load organizations.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03>
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
                const visibleTags = organization.tags.slice(0, 2);
                const remainingTagCount = Math.max(
                  0,
                  organization.tags.length - 2
                );
                const detailsRow =
                  [
                    organization.sector,
                    organization.location,
                    organization.size,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "No additional details";

                return (
                  <Link
                    key={organization.id}
                    href={`/app/crm/organizations/${organization.id}`}
                    className="block"
                  >
                    <Card
                      variant="secondary"
                      className="gap-2 transition-colors hover:bg-background-tint-02"
                    >
                      <div className="flex items-start gap-3">
                        <OrgAvatar
                          name={organization.name}
                          type={organization.type}
                        />

                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <Text as="p" mainUiAction text02>
                              {organization.name}
                            </Text>
                            <TypeBadge type={organization.type} />
                          </div>

                          <Text as="p" secondaryBody text03>
                            {detailsRow}
                          </Text>

                          <div className="flex items-center gap-1">
                            <SvgGlobe size={14} className="stroke-text-03" />
                            <Text as="p" secondaryBody text03>
                              {websiteLabel(organization.website)}
                            </Text>
                          </div>

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
