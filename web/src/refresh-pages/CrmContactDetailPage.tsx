"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgUser } from "@opal/icons";
import { CrmContactStatus, patchCrmContact } from "@/app/app/crm/crmService";
import { useCrmContact } from "@/lib/hooks/useCrmContact";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import CrmNav from "@/refresh-pages/crm/CrmNav";

const INTERACTIONS_PAGE_SIZE = 25;
const CONTACT_STATUSES: CrmContactStatus[] = [
  "lead",
  "active",
  "inactive",
  "archived",
];

interface ContactEditValues {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  status: CrmContactStatus;
  notes: string;
  linkedin_url: string;
  location: string;
}

const contactEditValidationSchema = Yup.object().shape({
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

function formatDate(value: string | null): string {
  if (!value) {
    return "No date";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "No date";
  }
  return parsed.toLocaleString();
}

export default function CrmContactDetailPage({
  contactId,
}: CrmContactDetailPageProps) {
  const router = useRouter();
  const [interactionsPageNum, setInteractionsPageNum] = useState(0);

  const { contact, isLoading, error, refreshContact } = useCrmContact(contactId);
  const {
    interactions,
    totalItems: totalInteractions,
    isLoading: isLoadingInteractions,
    error: interactionsError,
  } = useCrmInteractions({
    contactId,
    pageNum: interactionsPageNum,
    pageSize: INTERACTIONS_PAGE_SIZE,
  });

  const hasPrevInteractionsPage = interactionsPageNum > 0;
  const hasNextInteractionsPage =
    (interactionsPageNum + 1) * INTERACTIONS_PAGE_SIZE < totalInteractions;

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgUser}
          title={contact?.full_name || "CRM Contact"}
          description="Edit contact details and review interaction history."
          backButton
          onBack={() => router.back()}
        >
          <CrmNav />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
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
            <Formik<ContactEditValues>
              enableReinitialize
              initialValues={{
                first_name: contact.first_name,
                last_name: contact.last_name || "",
                email: contact.email || "",
                phone: contact.phone || "",
                title: contact.title || "",
                status: contact.status,
                notes: contact.notes || "",
                linkedin_url: contact.linkedin_url || "",
                location: contact.location || "",
              }}
              validationSchema={contactEditValidationSchema}
              onSubmit={async (values, { setStatus }) => {
                try {
                  await patchCrmContact(contact.id, {
                    first_name: values.first_name.trim(),
                    last_name: optionalText(values.last_name),
                    email: optionalText(values.email),
                    phone: optionalText(values.phone),
                    title: optionalText(values.title),
                    status: values.status,
                    notes: optionalText(values.notes),
                    linkedin_url: optionalText(values.linkedin_url),
                    location: optionalText(values.location),
                  });
                  await refreshContact();
                  setStatus("Contact saved.");
                } catch {
                  setStatus("Failed to update contact.");
                }
              }}
            >
              {({ isSubmitting, status }) => (
                <Form className="flex flex-col gap-2 rounded-12 border border-border-subtle p-3">
                  <Text as="p" mainUiAction text02>
                    Contact Details
                  </Text>

                  <div className="grid gap-2 md:grid-cols-2">
                    <InputTypeInField name="first_name" placeholder="First name" />
                    <InputTypeInField name="last_name" placeholder="Last name" />
                    <InputTypeInField name="email" placeholder="Email" />
                    <InputTypeInField name="phone" placeholder="Phone" />
                    <InputTypeInField name="title" placeholder="Title" />
                    <InputTypeInField name="location" placeholder="Location" />
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
                            {statusOption.toUpperCase()}
                          </InputSelect.Item>
                        ))}
                      </InputSelect.Content>
                    </InputSelectField>
                  </div>

                  <InputTextAreaField
                    name="notes"
                    placeholder="Notes"
                    rows={3}
                  />

                  {contact.organization_id && (
                    <Link
                      href={`/app/crm/organizations/${contact.organization_id}`}
                      className="w-fit"
                    >
                      <Text as="p" secondaryBody className="text-action-link-02">
                        View linked organization
                      </Text>
                    </Link>
                  )}

                  {status && (
                    <Text
                      as="p"
                      secondaryAction
                      className={
                        status.includes("Failed")
                          ? "text-status-error-03"
                          : "text-status-success-03"
                      }
                    >
                      {status}
                    </Text>
                  )}

                  <div className="flex justify-end">
                    <Button action primary type="submit" disabled={isSubmitting}>
                      {isSubmitting ? "Saving..." : "Save Contact"}
                    </Button>
                  </div>
                </Form>
              )}
            </Formik>
          ) : null}

          <div className="flex flex-col gap-2">
            <Text as="p" mainUiAction text02>
              Interactions
            </Text>
            <Text as="p" secondaryAction text03>
              {totalInteractions} total
            </Text>
          </div>

          {interactionsError ? (
            <Text as="p" secondaryBody className="text-status-error-03">
              Failed to load interactions.
            </Text>
          ) : isLoadingInteractions ? (
            <Text as="p" secondaryBody text03>
              Loading interactions...
            </Text>
          ) : interactions.length === 0 ? (
            <Text as="p" secondaryBody text03>
              No interactions found.
            </Text>
          ) : (
            <div className="flex flex-col gap-2">
              {interactions.map((interaction) => (
                <div
                  key={interaction.id}
                  className="rounded-08 border border-border-subtle p-3"
                >
                  <Text as="p" mainUiAction text02>
                    {interaction.title}
                  </Text>
                  <Text as="p" secondaryBody text03>
                    {interaction.type.toUpperCase()} ·{" "}
                    {formatDate(interaction.occurred_at || interaction.created_at)}
                  </Text>
                  {interaction.summary && (
                    <Text as="p" secondaryBody text03>
                      {interaction.summary}
                    </Text>
                  )}
                  {interaction.organization_id && (
                    <Link
                      href={`/app/crm/organizations/${interaction.organization_id}`}
                      className="w-fit"
                    >
                      <Text as="p" secondaryBody className="text-action-link-02">
                        View organization
                      </Text>
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button
              action
              secondary
              size="md"
              type="button"
              disabled={!hasPrevInteractionsPage}
              onClick={() =>
                setInteractionsPageNum((value) => Math.max(0, value - 1))
              }
            >
              Previous
            </Button>
            <Text as="p" secondaryAction text03>
              Page {interactionsPageNum + 1}
            </Text>
            <Button
              action
              secondary
              size="md"
              type="button"
              disabled={!hasNextInteractionsPage}
              onClick={() => setInteractionsPageNum((value) => value + 1)}
            >
              Next
            </Button>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </AppLayouts.Root>
  );
}
