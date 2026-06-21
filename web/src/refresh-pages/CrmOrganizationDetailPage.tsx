"use client";

import { Form, Formik } from "formik";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import * as Yup from "yup";

import {
  CrmInteraction,
  CrmOrganizationType,
  deleteCrmInteraction,
  deleteCrmOrganization,
  patchCrmOrganization,
} from "@/app/app/crm/crmService";
import { toast } from "@/hooks/useToast";
import * as AppLayouts from "@/layouts/app-layouts";
import { SettingsLayouts } from "@opal/layouts";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import { useInvalidateCrmCache } from "@/lib/hooks/useInvalidateCrmCache";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import { useCrmOrganization } from "@/lib/hooks/useCrmOrganization";
import { useUser } from "@/providers/UserProvider";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import Card from "@/refresh-components/cards/Card";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
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

import { Disabled } from "@opal/core";
import { Button as OpalButton } from "@opal/components";
import { SvgEdit, SvgOrganization, SvgTrash } from "@opal/icons";

const ORGANIZATION_TYPES: CrmOrganizationType[] = [
  "customer",
  "prospect",
  "partner",
  "vendor",
  "other",
];

const INTERACTION_PAGE_SIZE = 25;
const LINKED_CONTACTS_PAGE_SIZE = 5;

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
  website: Yup.string().trim().optional(),
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
  const { isAdmin } = useUser();
  const invalidateCrmCache = useInvalidateCrmCache();
  const [isEditing, setIsEditing] = useState(false);
  const [logInteractionModalOpen, setLogInteractionModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [isDeletingOrganization, setIsDeletingOrganization] = useState(false);
  const [interactionToDelete, setInteractionToDelete] =
    useState<CrmInteraction | null>(null);
  const [interactionToEdit, setInteractionToEdit] =
    useState<CrmInteraction | null>(null);
  const [isDeletingInteraction, setIsDeletingInteraction] = useState(false);
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
    includeContactInteractions: true,
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

  async function handleDeleteOrganization() {
    if (!organization || isDeletingOrganization) {
      return;
    }

    setIsDeletingOrganization(true);
    try {
      await deleteCrmOrganization(organization.id);
      await invalidateCrmCache();
      toast.success("Organization deleted.");
      setDeleteModalOpen(false);
      router.push("/app/crm/organizations");
    } catch (error) {
      console.error("Failed to delete CRM organization:", error);
      toast.error("Failed to delete organization.");
    } finally {
      setIsDeletingOrganization(false);
    }
  }

  async function handleDeleteInteraction() {
    if (!interactionToDelete || isDeletingInteraction) {
      return;
    }

    setIsDeletingInteraction(true);
    try {
      await deleteCrmInteraction(interactionToDelete.id);
      await invalidateCrmCache();
      void refreshInteractions();
      void refreshOrganization();
      toast.success("Interaction deleted.");
      setInteractionToDelete(null);
    } catch (error) {
      console.error("Failed to delete CRM interaction:", error);
      toast.error("Failed to delete interaction.");
    } finally {
      setIsDeletingInteraction(false);
    }
  }

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgOrganization}
          title="CRM"
          description="Organization Details"
          rightChildren={
            <Button
              action
              tertiary
              size="md"
              type="button"
              onClick={() => router.back()}
            >
              Back
            </Button>
          }
        >
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
                <div className="flex items-center gap-2">
                  {isAdmin && (
                    <IconButton
                      main
                      tertiary
                      icon={SvgTrash}
                      tooltip="Delete organization"
                      onClick={() => setDeleteModalOpen(true)}
                    />
                  )}
                  <Button
                    action
                    primary
                    type="button"
                    leftIcon={SvgEdit}
                    onClick={() => setIsEditing(true)}
                  >
                    Edit
                  </Button>
                </div>
              ))
            }
          />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          {error && (
            <Text as="p" secondaryBody className="text-sm text-status-error-03">
              Failed to load organization.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03 className="text-sm">
              Loading organization...
            </Text>
          ) : organization ? (
            <>
              <Card variant="secondary" className="[&>div]:items-stretch">
                <div className="flex items-start gap-3">
                  <OrgAvatar
                    name={organization.name}
                    type={organization.type}
                    size="lg"
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <Text as="p" headingH3>
                      {organization.name}
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
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <TypeBadge type={organization.type} />
                    <div className="flex flex-col items-end gap-0.5 text-sm text-text-03">
                      <span>
                        Created {formatRelativeDate(organization.created_at)}
                      </span>
                      <span>
                        Updated {formatRelativeDate(organization.updated_at)}
                      </span>
                    </div>
                  </div>
                </div>
              </Card>

              <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
                <div className="flex min-w-0 flex-[12] flex-col gap-4">
                  {isEditing ? (
                    <Card
                      variant="secondary"
                      className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start"
                    >
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
                            await invalidateCrmCache();
                            await refreshOrganization();
                            setIsEditing(false);
                          } catch {
                            setStatus("Failed to save organization.");
                          }
                        }}
                      >
                        {({ isSubmitting, status }) => (
                          <Form className="flex h-full flex-col gap-3">
                            <div className="grid w-full grid-cols-1 gap-3 md:grid-cols-2 md:[&>*]:min-w-0">
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Name
                                </Text>
                                <InputTypeInField
                                  name="name"
                                  placeholder="Organization name *"
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Website
                                </Text>
                                <InputTypeInField
                                  name="website"
                                  placeholder="Website URL"
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Type
                                </Text>
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
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Sector
                                </Text>
                                <InputTypeInField
                                  name="sector"
                                  placeholder="Sector"
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Location
                                </Text>
                                <InputTypeInField
                                  name="location"
                                  placeholder="Location"
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Size
                                </Text>
                                <InputTypeInField
                                  name="size"
                                  placeholder="Size"
                                />
                              </div>
                            </div>

                            <div className="mt-auto w-full border-t border-border-subtle" />

                            <div className="flex w-full flex-col gap-1">
                              <Text
                                as="p"
                                secondaryBody
                                text03
                                className="text-sm"
                              >
                                Notes
                              </Text>
                              <InputTextAreaField
                                name="notes"
                                placeholder="Notes"
                                rows={4}
                              />
                            </div>

                            {status && (
                              <Text
                                as="p"
                                secondaryBody
                                className="text-sm text-status-error-03"
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
                      className="gap-3 [&>div]:items-stretch"
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

                      <div className="w-full border-t border-border-subtle" />

                      <div className="flex w-full flex-col gap-1">
                        <Text as="p" mainUiAction text02>
                          Notes
                        </Text>
                        {organization.notes ? (
                          <Text
                            as="p"
                            className="whitespace-pre-wrap text-sm font-medium text-text-05"
                          >
                            {organization.notes}
                          </Text>
                        ) : (
                          <Text as="p" className="text-sm italic text-text-03">
                            -
                          </Text>
                        )}
                      </div>

                      <div className="w-full border-t border-border-subtle" />

                      <div className="flex w-full flex-col gap-2">
                        <Text as="p" mainUiAction text02>
                          Contacts In This Organization
                        </Text>

                        {linkedContactsLoading ? (
                          <Text as="p" secondaryBody text03 className="text-sm">
                            Loading contacts...
                          </Text>
                        ) : linkedContacts.length === 0 ? (
                          <Text
                            as="p"
                            secondaryBody
                            text03
                            className="text-sm italic"
                          >
                            No linked contacts yet.
                          </Text>
                        ) : (
                          <div className="flex w-full flex-col gap-2">
                            {linkedContacts.map((contact) => (
                              <Link
                                key={contact.id}
                                href={`/app/crm/contacts/${contact.id}`}
                                className="flex w-full items-center justify-between rounded-lg px-2 py-1 transition-colors hover:bg-background-tint-02"
                              >
                                <Text as="span" mainUiAction text02>
                                  {contact.full_name || contact.email || "Contact"}
                                </Text>
                                <div className="flex items-center gap-3">
                                  <Text
                                    as="span"
                                    secondaryBody
                                    text03
                                    className="text-sm"
                                  >
                                    {contact.title || "-"}
                                  </Text>
                                  <Text
                                    as="span"
                                    secondaryBody
                                    text03
                                    className="text-sm"
                                  >
                                    {contact.email || "-"}
                                  </Text>
                                </div>
                              </Link>
                            ))}
                            <Link
                              href={`/app/crm/contacts?organization_id=${organization.id}`}
                              className="inline-flex"
                            >
                              <Text
                                as="span"
                                secondaryBody
                                className="text-sm text-text-04 hover:underline"
                              >
                                View all contacts
                              </Text>
                            </Link>
                          </div>
                        )}
                      </div>
                    </Card>
                  )}
                </div>

                <div className="flex min-w-0 flex-[8] flex-col gap-4">
                  {interactionsError ? (
                    <Card variant="secondary">
                      <Text
                        as="p"
                        secondaryBody
                        className="text-sm text-status-error-03"
                      >
                        Failed to load activity.
                      </Text>
                    </Card>
                  ) : (
                    <Card variant="secondary" className="h-full min-h-[26rem]">
                      <ActivityTimeline
                        interactions={interactions}
                        isLoading={interactionsLoading}
                        hasMore={hasMoreInteractions}
                        canDeleteInteractions={isAdmin}
                        onDeleteInteraction={(interaction) => {
                          setInteractionToDelete(interaction);
                        }}
                        canEditInteractions={true}
                        onEditInteraction={(interaction) => {
                          setInteractionToEdit(interaction);
                        }}
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
                </div>
              </div>
            </>
          ) : null}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <LogInteractionModal
        open={logInteractionModalOpen}
        onOpenChange={setLogInteractionModalOpen}
        organizationId={organizationId}
        onSuccess={() => {
          void refreshInteractions();
          void refreshOrganization();
        }}
      />

      <LogInteractionModal
        open={interactionToEdit !== null}
        onOpenChange={(open) => {
          if (!open) {
            setInteractionToEdit(null);
          }
        }}
        interaction={interactionToEdit ?? undefined}
        organizationId={organizationId}
        onSuccess={() => {
          void refreshInteractions();
          void refreshOrganization();
        }}
      />

      {deleteModalOpen && organization && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Organization"
          onClose={
            isDeletingOrganization ? undefined : () => setDeleteModalOpen(false)
          }
          submit={
            <Disabled disabled={isDeletingOrganization}>
              <OpalButton
                variant="danger"
                onClick={() => void handleDeleteOrganization()}
              >
                {isDeletingOrganization ? "Deleting..." : "Delete Organization"}
              </OpalButton>
            </Disabled>
          }
        >
          <Text as="p" text03>
            Delete{" "}
            <Text as="span" text05>
              {organization.name}
            </Text>
            ? This action cannot be undone. Linked contacts and interactions
            will remain, but their organization link will be cleared.
          </Text>
        </ConfirmationModalLayout>
      )}

      {interactionToDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Interaction"
          onClose={
            isDeletingInteraction ? undefined : () => setInteractionToDelete(null)
          }
          submit={
            <Disabled disabled={isDeletingInteraction}>
              <OpalButton
                variant="danger"
                onClick={() => void handleDeleteInteraction()}
              >
                {isDeletingInteraction ? "Deleting..." : "Delete Interaction"}
              </OpalButton>
            </Disabled>
          }
        >
          <Text as="p" text03>
            Delete{" "}
            <Text as="span" text05>
              {interactionToDelete.title}
            </Text>
            ? This action cannot be undone.
          </Text>
        </ConfirmationModalLayout>
      )}
    </AppLayouts.Root>
  );
}
