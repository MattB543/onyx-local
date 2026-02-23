"use client";

import { Form, Formik } from "formik";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import {
  CrmContactSource,
  CrmContactStage,
  patchCrmContact,
} from "@/app/app/crm/crmService";
import useShareableUsers from "@/hooks/useShareableUsers";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useCrmContact } from "@/lib/hooks/useCrmContact";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import { useCrmOrganization } from "@/lib/hooks/useCrmOrganization";
import { useCrmSettings } from "@/lib/hooks/useCrmSettings";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import InputComboBoxField from "@/refresh-components/form/InputComboBoxField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputMultiSelect, {
  InputMultiSelectOption,
} from "@/refresh-components/inputs/InputMultiSelect";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import ActivityTimeline from "@/refresh-pages/crm/components/ActivityTimeline";
import ContactAvatar from "@/refresh-pages/crm/components/ContactAvatar";
import CrmBreadcrumbs from "@/refresh-pages/crm/components/CrmBreadcrumbs";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import DetailField from "@/refresh-pages/crm/components/DetailField";
import LogInteractionModal from "@/refresh-pages/crm/components/LogInteractionModal";
import StatusBadge from "@/refresh-pages/crm/components/StatusBadge";
import TagManager from "@/refresh-pages/crm/components/TagManager";
import CrmNav from "@/refresh-pages/crm/CrmNav";
import {
  CONTACT_SOURCES,
  contactValidationSchema,
  DEFAULT_CRM_CATEGORY_SUGGESTIONS,
  DEFAULT_CRM_STAGE_OPTIONS,
  formatCrmLabel,
  optionalText,
} from "@/refresh-pages/crm/crmOptions";

import { SvgEdit, SvgUser } from "@opal/icons";

const INTERACTION_PAGE_SIZE = 25;

interface ContactEditValues {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  location: string;
  linkedin_url: string;
  status: CrmContactStage;
  category: string;
  owner_ids: string[];
  source: CrmContactSource | "";
  notes: string;
}

interface CrmContactDetailPageProps {
  contactId: string;
}

export default function CrmContactDetailPage({
  contactId,
}: CrmContactDetailPageProps) {
  const router = useRouter();
  const [isEditing, setIsEditing] = useState(false);
  const [logInteractionModalOpen, setLogInteractionModalOpen] = useState(false);
  const [interactionPageSize, setInteractionPageSize] = useState(
    INTERACTION_PAGE_SIZE
  );

  const { contact, isLoading, error, refreshContact } =
    useCrmContact(contactId);
  const {
    interactions,
    totalItems: totalInteractions,
    isLoading: interactionsLoading,
    error: interactionsError,
    refreshInteractions,
  } = useCrmInteractions({
    contactId,
    pageNum: 0,
    pageSize: interactionPageSize,
  });
  const linkedOrganizationId = contact?.organization_id ?? null;
  const { organization: linkedOrganization } =
    useCrmOrganization(linkedOrganizationId);
  const { crmSettings } = useCrmSettings();
  const { data: usersData } = useShareableUsers({ includeApiKeys: false });

  const stageOptions = useMemo(
    () =>
      crmSettings?.contact_stage_options?.length
        ? crmSettings.contact_stage_options
        : DEFAULT_CRM_STAGE_OPTIONS,
    [crmSettings]
  );
  const categoryOptions = useMemo(
    () =>
      (crmSettings?.contact_category_suggestions?.length
        ? crmSettings.contact_category_suggestions
        : DEFAULT_CRM_CATEGORY_SUGGESTIONS
      ).map((category) => ({
        value: category,
        label: category,
      })),
    [crmSettings]
  );
  const ownerOptions = useMemo<InputMultiSelectOption[]>(
    () =>
      (usersData || []).map((candidate) => ({
        value: candidate.id,
        label: candidate.full_name?.trim() || candidate.email,
      })),
    [usersData]
  );
  const ownerLabelById = useMemo(
    () =>
      new Map(
        ownerOptions.map((ownerOption) => [
          ownerOption.value,
          ownerOption.label,
        ])
      ),
    [ownerOptions]
  );
  const attendeeUserNameById = useMemo(
    () =>
      new Map(
        (usersData || []).map((candidate) => [
          candidate.id,
          candidate.full_name?.trim() || candidate.email,
        ])
      ),
    [usersData]
  );
  const attendeeContactNameById = useMemo(() => {
    const labelById = new Map<string, string>();
    if (contact) {
      const fullName =
        contact.full_name?.trim() ||
        `${contact.first_name} ${contact.last_name || ""}`.trim() ||
        contact.email ||
        contact.id;
      labelById.set(contact.id, fullName);
    }
    return labelById;
  }, [contact]);

  const hasMoreInteractions = interactions.length < totalInteractions;

  const breadcrumbs = useMemo(
    () => [
      { label: "CRM", href: "/app/crm" },
      { label: "Contacts", href: "/app/crm/contacts" },
      { label: contact?.full_name || contact?.first_name || "Contact" },
    ],
    [contact?.first_name, contact?.full_name]
  );

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="xl">
        <SettingsLayouts.Header
          icon={SvgUser}
          title="CRM"
          description={<CrmBreadcrumbs items={breadcrumbs} />}
          titleIconInline
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
              contact &&
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
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          {error && (
            <Text as="p" secondaryBody className="text-sm text-status-error-03">
              Failed to load contact.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03 className="text-sm">
              Loading contact...
            </Text>
          ) : contact ? (
            <>
              <Card variant="secondary" className="[&>div]:items-stretch">
                <div className="flex w-full items-start gap-3">
                  <ContactAvatar
                    firstName={contact.first_name}
                    lastName={contact.last_name}
                    size="lg"
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="text-base font-semibold text-text-05">
                      {contact.full_name || contact.first_name}
                    </span>
                    <div className="flex min-w-0 flex-wrap items-center gap-1 text-sm text-text-03">
                      <span>{contact.title || "No title"}</span>
                      {contact.organization_id && (
                        <>
                          <span>·</span>
                          <Link
                            href={`/app/crm/organizations/${contact.organization_id}`}
                            className="truncate hover:underline"
                          >
                            {linkedOrganization?.name || "-"}
                          </Link>
                        </>
                      )}
                    </div>
                    <TagManager
                      entityType="contact"
                      entityId={contact.id}
                      tags={contact.tags}
                      showLabel={false}
                      onRefresh={() => {
                        void refreshContact();
                      }}
                    />
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

              <div className="flex flex-col gap-6 lg:flex-row lg:items-stretch">
                <div className="min-w-0 flex-1">
                  {isEditing ? (
                    <Card
                      variant="secondary"
                      className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start"
                    >
                      <Text as="p" mainUiAction text02>
                        Edit Contact
                      </Text>

                      <Formik<ContactEditValues>
                        enableReinitialize
                        initialValues={{
                          first_name: contact.first_name,
                          last_name: contact.last_name || "",
                          email: contact.email || "",
                          phone: contact.phone || "",
                          title: contact.title || "",
                          location: contact.location || "",
                          linkedin_url: contact.linkedin_url || "",
                          status: contact.status,
                          category: contact.category || "",
                          owner_ids: contact.owner_ids || [],
                          source: contact.source || "",
                          notes: contact.notes || "",
                        }}
                        validationSchema={contactValidationSchema}
                        onSubmit={async (values, { setStatus }) => {
                          try {
                            await patchCrmContact(contact.id, {
                              first_name: values.first_name.trim(),
                              last_name: optionalText(values.last_name),
                              email: optionalText(values.email),
                              phone: optionalText(values.phone),
                              title: optionalText(values.title),
                              location: optionalText(values.location),
                              linkedin_url: optionalText(values.linkedin_url),
                              status: values.status,
                              category: optionalText(values.category),
                              owner_ids: values.owner_ids,
                              source: values.source || undefined,
                              notes: optionalText(values.notes),
                            });
                            await refreshContact();
                            setIsEditing(false);
                          } catch {
                            setStatus("Failed to save contact.");
                          }
                        }}
                      >
                        {({ isSubmitting, status, values, setFieldValue }) => (
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
                                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                                  <InputTypeInField
                                    name="first_name"
                                    placeholder="First name *"
                                  />
                                  <InputTypeInField
                                    name="last_name"
                                    placeholder="Last name"
                                  />
                                </div>
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Email
                                </Text>
                                <InputTypeInField
                                  name="email"
                                  placeholder="Email"
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Title
                                </Text>
                                <InputTypeInField
                                  name="title"
                                  placeholder="Title"
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Organization
                                </Text>
                                <InputTypeIn
                                  value={
                                    linkedOrganization?.name ||
                                    (contact.organization_id
                                      ? "Linked organization"
                                      : "")
                                  }
                                  placeholder="No organization"
                                  variant="readOnly"
                                  readOnly
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Phone
                                </Text>
                                <InputTypeInField
                                  name="phone"
                                  placeholder="Phone"
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
                                  Source
                                </Text>
                                <InputSelectField name="source">
                                  <InputSelect.Trigger placeholder="Source" />
                                  <InputSelect.Content>
                                    {CONTACT_SOURCES.map((source) => (
                                      <InputSelect.Item
                                        key={source}
                                        value={source}
                                      >
                                        {formatCrmLabel(source)}
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
                                  Category
                                </Text>
                                <InputComboBoxField
                                  name="category"
                                  options={categoryOptions}
                                  strict={false}
                                  placeholder="Category"
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  LinkedIn
                                </Text>
                                <InputTypeInField
                                  name="linkedin_url"
                                  placeholder="LinkedIn URL"
                                />
                              </div>
                              <div className="flex flex-col gap-1">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Status
                                </Text>
                                <InputSelectField name="status">
                                  <InputSelect.Trigger placeholder="Status" />
                                  <InputSelect.Content>
                                    {stageOptions.map((statusOption) => (
                                      <InputSelect.Item
                                        key={statusOption}
                                        value={statusOption}
                                      >
                                        {formatCrmLabel(statusOption)}
                                      </InputSelect.Item>
                                    ))}
                                  </InputSelect.Content>
                                </InputSelectField>
                              </div>
                              <div className="flex w-full flex-col gap-1 md:col-span-2">
                                <Text
                                  as="p"
                                  secondaryBody
                                  text03
                                  className="text-sm"
                                >
                                  Owners
                                </Text>
                                <InputMultiSelect
                                  value={values.owner_ids}
                                  onChange={(nextOwnerIds) => {
                                    setFieldValue("owner_ids", nextOwnerIds);
                                  }}
                                  options={ownerOptions}
                                  placeholder="Select owner(s)"
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
                                {isSubmitting ? "Saving..." : "Save Contact"}
                              </Button>
                            </div>
                          </Form>
                        )}
                      </Formik>
                    </Card>
                  ) : (
                    <Card
                      variant="secondary"
                      className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start"
                    >
                      <Text as="p" mainUiAction text02 className="w-full">
                        Details
                      </Text>
                      <div className="grid w-full grid-cols-1 gap-3 md:grid-cols-2 md:[&>*]:min-w-0">
                        <DetailField
                          label="Name"
                          value={contact.full_name || contact.first_name}
                          layout="stacked"
                        />
                        <DetailField
                          label="Email"
                          value={contact.email}
                          type="email"
                          layout="stacked"
                        />
                        <DetailField
                          label="Title"
                          value={contact.title}
                          layout="stacked"
                        />
                        <DetailField
                          label="Organization"
                          value={
                            contact.organization_id
                              ? linkedOrganization?.name ||
                                "Linked organization"
                              : null
                          }
                          type={contact.organization_id ? "org-link" : "text"}
                          href={
                            contact.organization_id
                              ? `/app/crm/organizations/${contact.organization_id}`
                              : undefined
                          }
                          layout="stacked"
                        />
                        <DetailField
                          label="Phone"
                          value={contact.phone}
                          type="phone"
                          layout="stacked"
                        />
                        <DetailField
                          label="Location"
                          value={contact.location}
                          layout="stacked"
                        />
                        <DetailField
                          label="Source"
                          value={
                            contact.source
                              ? formatCrmLabel(contact.source)
                              : null
                          }
                          layout="stacked"
                        />
                        <DetailField
                          label="Category"
                          value={contact.category}
                          layout="stacked"
                        />
                        <DetailField
                          label="LinkedIn"
                          value={contact.linkedin_url}
                          type="link"
                          layout="stacked"
                        />
                        <DetailField
                          label="Owners"
                          value={
                            contact.owner_ids.length > 0
                              ? contact.owner_ids
                                  .map(
                                    (ownerId) =>
                                      ownerLabelById.get(ownerId) ||
                                      `Unknown User (${ownerId.slice(0, 8)})`
                                  )
                                  .join(", ")
                              : null
                          }
                          layout="stacked"
                        />
                      </div>

                      <div className="mt-auto w-full border-t border-border-subtle" />

                      <div className="flex w-full flex-col gap-1">
                        <Text as="p" mainUiAction text02>
                          Notes
                        </Text>
                        {contact.notes ? (
                          <Text
                            as="p"
                            className="whitespace-pre-wrap text-sm font-medium text-text-05"
                          >
                            {contact.notes}
                          </Text>
                        ) : (
                          <Text as="p" className="text-sm italic text-text-03">
                            -
                          </Text>
                        )}
                      </div>
                    </Card>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  {interactionsError ? (
                    <Card
                      variant="secondary"
                      className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start"
                    >
                      <Text
                        as="p"
                        secondaryBody
                        className="w-full text-sm text-status-error-03"
                      >
                        Failed to load activity.
                      </Text>
                    </Card>
                  ) : (
                    <Card
                      variant="secondary"
                      className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start"
                    >
                      <ActivityTimeline
                        interactions={interactions}
                        isLoading={interactionsLoading}
                        hasMore={hasMoreInteractions}
                        attendeeUserNameById={attendeeUserNameById}
                        attendeeContactNameById={attendeeContactNameById}
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
        contactId={contactId}
        onSuccess={() => {
          void refreshInteractions();
          void refreshContact();
        }}
      />
    </AppLayouts.Root>
  );
}
