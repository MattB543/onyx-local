"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgUser } from "@opal/icons";
import { CrmContactStatus, createCrmContact } from "@/app/app/crm/crmService";
import { useCrmContacts } from "@/lib/hooks/useCrmContacts";
import CrmNav from "@/refresh-pages/crm/CrmNav";

const PAGE_SIZE = 25;
const CONTACT_STATUSES: CrmContactStatus[] = [
  "lead",
  "active",
  "inactive",
  "archived",
];

interface ContactCreateValues {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  status: CrmContactStatus;
  notes: string;
}

const contactCreateValidationSchema = Yup.object().shape({
  first_name: Yup.string().trim().required("First name is required."),
  email: Yup.string().trim().email("Enter a valid email.").optional(),
});

function optionalText(value: string): string | undefined {
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

export default function CrmContactsPage() {
  const searchParams = useSearchParams();
  const organizationIdFilter = searchParams.get("organization_id") ?? undefined;

  const [searchText, setSearchText] = useState("");
  const [pageNum, setPageNum] = useState(0);
  const [showCreateForm, setShowCreateForm] = useState(false);

  const { contacts, totalItems, isLoading, error, refreshContacts } =
    useCrmContacts({
      q: searchText,
      organizationId: organizationIdFilter,
      pageNum,
      pageSize: PAGE_SIZE,
    });

  const hasPrev = pageNum > 0;
  const hasNext = (pageNum + 1) * PAGE_SIZE < totalItems;

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgUser}
          title="CRM"
          description="Manage contacts and organizations."
          rightChildren={
            <Button
              action
              primary
              size="md"
              type="button"
              onClick={() => setShowCreateForm((previous) => !previous)}
            >
              {showCreateForm ? "Cancel" : "New Contact"}
            </Button>
          }
        >
          <CrmNav />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          {showCreateForm && (
            <Formik<ContactCreateValues>
              initialValues={{
                first_name: "",
                last_name: "",
                email: "",
                phone: "",
                title: "",
                status: "lead",
                notes: "",
              }}
              validationSchema={contactCreateValidationSchema}
              onSubmit={async (values, { resetForm, setStatus }) => {
                try {
                  await createCrmContact({
                    first_name: values.first_name.trim(),
                    last_name: optionalText(values.last_name),
                    email: optionalText(values.email),
                    phone: optionalText(values.phone),
                    title: optionalText(values.title),
                    status: values.status,
                    notes: optionalText(values.notes),
                    organization_id: organizationIdFilter,
                  });
                  await refreshContacts();
                  resetForm();
                  setShowCreateForm(false);
                } catch {
                  setStatus("Failed to create contact.");
                }
              }}
            >
              {({ isSubmitting, status }) => (
                <Form className="flex flex-col gap-2 rounded-12 border border-border-subtle p-3">
                  <Text as="p" mainUiAction text02>
                    Create Contact
                  </Text>

                  <div className="grid gap-2 md:grid-cols-2">
                    <InputTypeInField name="first_name" placeholder="First name" />
                    <InputTypeInField name="last_name" placeholder="Last name" />
                    <InputTypeInField name="email" placeholder="Email" />
                    <InputTypeInField name="phone" placeholder="Phone" />
                    <InputTypeInField name="title" placeholder="Title" />
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

                  {status && (
                    <Text
                      as="p"
                      secondaryAction
                      text05
                      className="text-status-error-03"
                    >
                      {status}
                    </Text>
                  )}

                  <div className="flex justify-end">
                    <Button action primary type="submit" disabled={isSubmitting}>
                      {isSubmitting ? "Creating..." : "Create Contact"}
                    </Button>
                  </div>
                </Form>
              )}
            </Formik>
          )}

          <div className="flex items-center gap-2">
            <InputTypeIn
              value={searchText}
              onChange={(event) => {
                setSearchText(event.target.value);
                setPageNum(0);
              }}
              placeholder="Search contacts"
              leftSearchIcon
            />
            <Text as="p" secondaryAction text03>
              {totalItems} total
            </Text>
          </div>

          {organizationIdFilter && (
            <div className="flex items-center justify-between rounded-08 border border-border-subtle p-2">
              <Text as="p" secondaryBody text03>
                Filtered to one organization.
              </Text>
              <Button action tertiary href="/app/crm/contacts" size="md">
                Clear Filter
              </Button>
            </div>
          )}

          {error && (
            <Text as="p" secondaryBody className="text-status-error-03">
              Failed to load CRM contacts.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03>
              Loading contacts...
            </Text>
          ) : contacts.length === 0 ? (
            <Text as="p" secondaryBody text03>
              No contacts found.
            </Text>
          ) : (
            <div className="flex flex-col gap-2">
              {contacts.map((contact) => (
                <Link
                  key={contact.id}
                  href={`/app/crm/contacts/${contact.id}`}
                  className="rounded-08 border border-border-subtle p-3 hover:bg-background-tint-02"
                >
                  <Text as="p" mainUiAction text02>
                    {contact.full_name || contact.first_name}
                  </Text>
                  <Text as="p" secondaryBody text03>
                    {contact.email || "No email"}
                  </Text>
                  <Text as="p" secondaryBody text03>
                    {contact.title || "No title"}
                  </Text>
                  {contact.organization_id && (
                    <Text as="p" secondaryBody className="text-action-link-02">
                      Linked organization
                    </Text>
                  )}
                </Link>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button
              action
              secondary
              size="md"
              type="button"
              disabled={!hasPrev}
              onClick={() => setPageNum((value) => Math.max(0, value - 1))}
            >
              Previous
            </Button>
            <Text as="p" secondaryAction text03>
              Page {pageNum + 1}
            </Text>
            <Button
              action
              secondary
              size="md"
              type="button"
              disabled={!hasNext}
              onClick={() => setPageNum((value) => value + 1)}
            >
              Next
            </Button>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </AppLayouts.Root>
  );
}
