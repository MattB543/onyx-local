"use client";

import { Form, Formik } from "formik";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import * as Yup from "yup";

import {
  CrmContactSource,
  CrmContactStatus,
  patchCrmContact,
} from "@/app/app/crm/crmService";
import * as AppLayouts from "@/layouts/app-layouts";
import { useCrmContact } from "@/lib/hooks/useCrmContact";
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
import ContactAvatar from "@/refresh-pages/crm/components/ContactAvatar";
import CrmBreadcrumbs from "@/refresh-pages/crm/components/CrmBreadcrumbs";
import { formatRelativeDate } from "@/refresh-pages/crm/components/crmDateUtils";
import DetailField from "@/refresh-pages/crm/components/DetailField";
import LogInteractionModal from "@/refresh-pages/crm/components/LogInteractionModal";
import StatusBadge from "@/refresh-pages/crm/components/StatusBadge";
import TagManager from "@/refresh-pages/crm/components/TagManager";
import CrmNav from "@/refresh-pages/crm/CrmNav";

import { SvgEdit } from "@opal/icons";

const CONTACT_STATUSES: CrmContactStatus[] = [
  "lead",
  "active",
  "inactive",
  "archived",
];

const CONTACT_SOURCES: CrmContactSource[] = [
  "manual",
  "import",
  "referral",
  "inbound",
  "other",
];

const INTERACTION_PAGE_SIZE = 25;

interface ContactEditValues {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  location: string;
  linkedin_url: string;
  status: CrmContactStatus;
  source: CrmContactSource | "";
  notes: string;
}

const validationSchema = Yup.object().shape({
  first_name: Yup.string().trim().required("First name is required."),
  email: Yup.string().trim().email("Enter a valid email.").optional(),
});

interface CrmContactDetailPageProps {
  contactId: string;
}

function optionalText(value: string): string | undefined {
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

function formatLabel(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
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
          </div>

          {error && (
            <Text as="p" secondaryBody className="text-status-error-03">
              Failed to load contact.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03>
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
                      <span>{contact.title || "-"}</span>
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
                    <span className="text-xs text-text-03">
                      Created{" "}
                      {formatRelativeDate(contact.created_at)} · Updated{" "}
                      {formatRelativeDate(contact.updated_at)}
                    </span>
                  </div>
                </div>
              </Card>

              <div className="flex flex-col gap-6 lg:flex-row lg:items-stretch">
                <div className="min-w-0 flex-1">
                  {isEditing ? (
                    <Card variant="secondary" className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start">
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
                          source: contact.source || "",
                          notes: contact.notes || "",
                        }}
                        validationSchema={validationSchema}
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
                        {({ isSubmitting, status }) => (
                          <Form className="flex flex-col gap-3">
                            <div className="grid gap-2 md:grid-cols-2">
                              <InputTypeInField
                                name="first_name"
                                placeholder="First name *"
                              />
                              <InputTypeInField
                                name="last_name"
                                placeholder="Last name"
                              />
                              <InputTypeInField
                                name="email"
                                placeholder="Email"
                              />
                              <InputTypeInField
                                name="phone"
                                placeholder="Phone"
                              />
                              <InputTypeInField
                                name="title"
                                placeholder="Title"
                              />
                              <InputTypeInField
                                name="location"
                                placeholder="Location"
                              />
                              <InputTypeInField
                                name="linkedin_url"
                                placeholder="LinkedIn URL"
                              />
                              <InputSelectField name="status">
                                <InputSelect.Trigger placeholder="Status" />
                                <InputSelect.Content>
                                  {CONTACT_STATUSES.map((statusOption) => (
                                    <InputSelect.Item
                                      key={statusOption}
                                      value={statusOption}
                                    >
                                      {formatLabel(statusOption)}
                                    </InputSelect.Item>
                                  ))}
                                </InputSelect.Content>
                              </InputSelectField>
                              <InputSelectField name="source">
                                <InputSelect.Trigger placeholder="Source" />
                                <InputSelect.Content>
                                  {CONTACT_SOURCES.map((source) => (
                                    <InputSelect.Item
                                      key={source}
                                      value={source}
                                    >
                                      {formatLabel(source)}
                                    </InputSelect.Item>
                                  ))}
                                </InputSelect.Content>
                              </InputSelectField>
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
                                {isSubmitting ? "Saving..." : "Save Contact"}
                              </Button>
                            </div>
                          </Form>
                        )}
                      </Formik>
                    </Card>
                  ) : (
                    <Card variant="secondary" className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start">
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
                            contact.source ? formatLabel(contact.source) : null
                          }
                          layout="stacked"
                        />
                        <DetailField
                          label="LinkedIn"
                          value={contact.linkedin_url}
                          type="link"
                          layout="stacked"
                        />
                      </div>

                      <div className="mt-auto w-full border-t border-border-subtle" />

                      <div className="flex w-full flex-col gap-1">
                        <Text as="p" mainUiAction text02>
                          Notes
                        </Text>
                        {contact.notes ? (
                          <Text as="p" secondaryBody text03>
                            {contact.notes}
                          </Text>
                        ) : (
                          <Text as="p" secondaryBody text03 className="italic">
                            -
                          </Text>
                        )}
                      </div>
                    </Card>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  {interactionsError ? (
                    <Card variant="secondary" className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start">
                      <Text
                        as="p"
                        secondaryBody
                        className="w-full text-status-error-03"
                      >
                        Failed to load activity.
                      </Text>
                    </Card>
                  ) : (
                    <Card variant="secondary" className="h-full [&>div]:items-stretch [&>div]:h-full [&>div]:justify-start">
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
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>

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
