"use client";

import { Form, Formik } from "formik";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import * as Yup from "yup";

import {
  CrmOrganizationType,
  patchCrmOrganization,
} from "@/app/app/crm/crmService";
import * as AppLayouts from "@/layouts/app-layouts";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import { useCrmOrganization } from "@/lib/hooks/useCrmOrganization";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import ActivityTimeline from "@/refresh-pages/crm/components/ActivityTimeline";
import CrmBreadcrumbs from "@/refresh-pages/crm/components/CrmBreadcrumbs";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import DetailField from "@/refresh-pages/crm/components/DetailField";
import LogInteractionModal from "@/refresh-pages/crm/components/LogInteractionModal";
import OrgAvatar from "@/refresh-pages/crm/components/OrgAvatar";
import TagManager from "@/refresh-pages/crm/components/TagManager";
import TypeBadge from "@/refresh-pages/crm/components/TypeBadge";
import CrmNav from "@/refresh-pages/crm/CrmNav";

import { SvgEdit } from "@opal/icons";

const ORGANIZATION_TYPES: CrmOrganizationType[] = [
  "customer",
  "prospect",
  "partner",
  "vendor",
  "other",
];

const INTERACTION_PAGE_SIZE = 25;
const LINKED_CONTACTS_PAGE_SIZE = 5;
const DETAILS_CARD_MIN_HEIGHT = "min-h-[26rem]";

interface OrganizationEditValues {
  name: string;
  website: string;
  type: CrmOrganizationType | "";
  sector: string;
  location: string;
  size: string;
  notes: string;
}

const validationSchema = Yup.object().shape({
  name: Yup.string().trim().required("Organization name is required."),
  website: Yup.string().trim().url("Enter a valid URL.").optional(),
});

interface CrmOrganizationDetailPageProps {
  organizationId: string;
}

function optionalText(value: string): string | undefined {
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

function formatLabel(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function CrmOrganizationDetailPage({
  organizationId,
}: CrmOrganizationDetailPageProps) {
  const router = useRouter();
  const [isEditing, setIsEditing] = useState(false);
  const [logInteractionModalOpen, setLogInteractionModalOpen] = useState(false);
  const [interactionPageSize, setInteractionPageSize] = useState(
    INTERACTION_PAGE_SIZE
  );

  const { organization, isLoading, error, refreshOrganization } =
    useCrmOrganization(organizationId);
  const {
    interactions,
    totalItems: totalInteractions,
    isLoading: interactionsLoading,
    error: interactionsError,
    refreshInteractions,
  } = useCrmInteractions({
    organizationId,
    pageNum: 0,
    pageSize: interactionPageSize,
  });
  const { contacts: linkedContacts, isLoading: linkedContactsLoading } =
    useCrmContacts({
      organizationId,
      pageNum: 0,
      pageSize: LINKED_CONTACTS_PAGE_SIZE,
    });

  const hasMoreInteractions = interactions.length < totalInteractions;

  const breadcrumbs = useMemo(
    () => [
      { label: "CRM", href: "/app/crm" },
      { label: "Organizations", href: "/app/crm/organizations" },
      { label: organization?.name || "Organization" },
    ],
    [organization?.name]
  );

  return (
    <AppLayouts.Root>
      <div className="h-full w-full overflow-y-auto">
        <div className="mx-auto flex w-[min(72rem,100%)] flex-col gap-6 px-4 pb-12 pt-8">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <CrmBreadcrumbs items={breadcrumbs} />
              <Button
                action
                tertiary
                size="md"
                type="button"
                onClick={() => router.back()}
              >
                Back
              </Button>
            </div>

            <CrmNav
              rightContent={
                organization &&
                (isEditing ? (
                  <Button
                    action
                    secondary
                    type="button"
                    onClick={() => setIsEditing(false)}
                  >
                    Cancel Edit
                  </Button>
                ) : (
                  <Button
                    action
                    primary
                    type="button"
                    leftIcon={SvgEdit}
                    onClick={() => setIsEditing(true)}
                  >
                    Edit
                  </Button>
                ))
              }
            />
          </div>

          {error && (
            <Text as="p" secondaryBody className="text-status-error-03">
              Failed to load organization.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03>
              Loading organization...
            </Text>
          ) : organization ? (
            <>
              <Card variant="secondary" className="gap-3">
                <div className="flex items-start gap-3">
                  <OrgAvatar
                    name={organization.name}
                    type={organization.type}
                    size="lg"
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Text as="p" headingH3>
                        {organization.name}
                      </Text>
                      <TypeBadge type={organization.type} />
                    </div>
                    <Text as="p" secondaryBody text03>
                      Created {formatRelativeDate(organization.created_at)} ·
                      Updated {formatRelativeDate(organization.updated_at)}
                    </Text>
                    <TagManager
                      entityType="organization"
                      entityId={organization.id}
                      tags={organization.tags}
                      showLabel={false}
                      onRefresh={() => {
                        void refreshOrganization();
                      }}
                    />
                  </div>
                </div>
              </Card>

              <div className="flex flex-col gap-6 lg:flex-row">
                <div className="flex min-w-0 flex-[11] flex-col gap-4">
                  {isEditing ? (
                    <Card variant="secondary" className="gap-3">
                      <Text as="p" mainUiAction text02>
                        Edit Organization
                      </Text>

                      <Formik<OrganizationEditValues>
                        enableReinitialize
                        initialValues={{
                          name: organization.name,
                          website: organization.website || "",
                          type: organization.type || "",
                          sector: organization.sector || "",
                          location: organization.location || "",
                          size: organization.size || "",
                          notes: organization.notes || "",
                        }}
                        validationSchema={validationSchema}
                        onSubmit={async (values, { setStatus }) => {
                          try {
                            await patchCrmOrganization(organization.id, {
                              name: values.name.trim(),
                              website: optionalText(values.website),
                              type: values.type || undefined,
                              sector: optionalText(values.sector),
                              location: optionalText(values.location),
                              size: optionalText(values.size),
                              notes: optionalText(values.notes),
                            });
                            await refreshOrganization();
                            setIsEditing(false);
                          } catch {
                            setStatus("Failed to save organization.");
                          }
                        }}
                      >
                        {({ isSubmitting, status }) => (
                          <Form className="flex flex-col gap-3">
                            <div className="grid gap-2 md:grid-cols-2">
                              <InputTypeInField
                                name="name"
                                placeholder="Organization name *"
                              />
                              <InputTypeInField
                                name="website"
                                placeholder="Website URL"
                              />
                              <InputSelectField name="type">
                                <InputSelect.Trigger placeholder="Type" />
                                <InputSelect.Content>
                                  {ORGANIZATION_TYPES.map((typeOption) => (
                                    <InputSelect.Item
                                      key={typeOption}
                                      value={typeOption}
                                    >
                                      {formatLabel(typeOption)}
                                    </InputSelect.Item>
                                  ))}
                                </InputSelect.Content>
                              </InputSelectField>
                              <InputTypeInField
                                name="sector"
                                placeholder="Sector"
                              />
                              <InputTypeInField
                                name="location"
                                placeholder="Location"
                              />
                              <InputTypeInField
                                name="size"
                                placeholder="Size"
                              />
                            </div>

                            <InputTextAreaField
                              name="notes"
                              placeholder="Notes"
                              rows={4}
                            />

                            {status && (
                              <Text
                                as="p"
                                secondaryBody
                                className="text-status-error-03"
                              >
                                {status}
                              </Text>
                            )}

                            <div className="flex justify-end">
                              <Button
                                action
                                primary
                                size="md"
                                type="submit"
                                disabled={isSubmitting}
                              >
                                {isSubmitting
                                  ? "Saving..."
                                  : "Save Organization"}
                              </Button>
                            </div>
                          </Form>
                        )}
                      </Formik>
                    </Card>
                  ) : (
                    <Card
                      variant="secondary"
                      className={`gap-3 ${DETAILS_CARD_MIN_HEIGHT}`}
                    >
                      <Text as="p" mainUiAction text02>
                        Details
                      </Text>
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 md:[&>*]:min-w-0">
                        <DetailField
                          label="Name"
                          value={organization.name}
                          layout="stacked"
                        />
                        <DetailField
                          label="Website"
                          value={organization.website}
                          type="link"
                          layout="stacked"
                        />
                        <DetailField
                          label="Type"
                          value={
                            organization.type
                              ? formatLabel(organization.type)
                              : null
                          }
                          layout="stacked"
                        />
                        <DetailField
                          label="Sector"
                          value={organization.sector}
                          layout="stacked"
                        />
                        <DetailField
                          label="Location"
                          value={organization.location}
                          layout="stacked"
                        />
                        <DetailField
                          label="Size"
                          value={organization.size}
                          layout="stacked"
                        />
                      </div>
                    </Card>
                  )}
                </div>

                <div className="flex min-w-0 flex-[9] flex-col gap-4">
                  {interactionsError ? (
                    <Card variant="secondary">
                      <Text
                        as="p"
                        secondaryBody
                        className="text-status-error-03"
                      >
                        Failed to load activity.
                      </Text>
                    </Card>
                  ) : (
                    <Card
                      variant="secondary"
                      className={DETAILS_CARD_MIN_HEIGHT}
                    >
                      <ActivityTimeline
                        interactions={interactions}
                        isLoading={interactionsLoading}
                        hasMore={hasMoreInteractions}
                        onLoadMore={() =>
                          setInteractionPageSize(
                            (value) => value + INTERACTION_PAGE_SIZE
                          )
                        }
                        onLogInteraction={() =>
                          setLogInteractionModalOpen(true)
                        }
                      />
                    </Card>
                  )}

                  <Card variant="secondary" className="gap-2">
                    <Text as="p" mainUiAction text02>
                      Contacts In This Organization
                    </Text>

                    {linkedContactsLoading ? (
                      <Text as="p" secondaryBody text03>
                        Loading contacts...
                      </Text>
                    ) : linkedContacts.length === 0 ? (
                      <Text as="p" secondaryBody text03 className="italic">
                        No linked contacts yet.
                      </Text>
                    ) : (
                      <div className="flex flex-col gap-1.5">
                        {linkedContacts.map((contact) => (
                          <Link
                            key={contact.id}
                            href={`/app/crm/contacts/${contact.id}`}
                            className="inline-flex"
                          >
                            <Text
                              as="span"
                              secondaryBody
                              className="text-text-04 hover:underline"
                            >
                              {contact.full_name || contact.first_name}
                            </Text>
                          </Link>
                        ))}
                        <Link
                          href={`/app/crm/contacts?organization_id=${organization.id}`}
                          className="inline-flex"
                        >
                          <Text
                            as="span"
                            secondaryBody
                            className="text-text-04 hover:underline"
                          >
                            View all contacts
                          </Text>
                        </Link>
                      </div>
                    )}
                  </Card>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>

      <LogInteractionModal
        open={logInteractionModalOpen}
        onOpenChange={setLogInteractionModalOpen}
        organizationId={organizationId}
        onSuccess={() => {
          void refreshInteractions();
          void refreshOrganization();
        }}
      />
    </AppLayouts.Root>
  );
}
