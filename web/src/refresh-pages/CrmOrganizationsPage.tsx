"use client";

import Link from "next/link";
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
import {
  CrmOrganizationType,
  createCrmOrganization,
} from "@/app/app/crm/crmService";
import { useCrmOrganizations } from "@/lib/hooks/useCrmOrganizations";
import CrmNav from "@/refresh-pages/crm/CrmNav";

const PAGE_SIZE = 25;
const ORGANIZATION_TYPES: CrmOrganizationType[] = [
  "customer",
  "prospect",
  "partner",
  "vendor",
  "other",
];

interface OrganizationCreateValues {
  name: string;
  website: string;
  type: CrmOrganizationType | "";
  sector: string;
  location: string;
  size: string;
  notes: string;
}

const organizationCreateValidationSchema = Yup.object().shape({
  name: Yup.string().trim().required("Organization name is required."),
  website: Yup.string().trim().url("Enter a valid URL.").optional(),
});

function optionalText(value: string): string | undefined {
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

export default function CrmOrganizationsPage() {
  const [searchText, setSearchText] = useState("");
  const [pageNum, setPageNum] = useState(0);
  const [showCreateForm, setShowCreateForm] = useState(false);

  const { organizations, totalItems, isLoading, error, refreshOrganizations } =
    useCrmOrganizations({
      q: searchText,
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
              {showCreateForm ? "Cancel" : "New Organization"}
            </Button>
          }
        >
          <CrmNav />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
          {showCreateForm && (
            <Formik<OrganizationCreateValues>
              initialValues={{
                name: "",
                website: "",
                type: "",
                sector: "",
                location: "",
                size: "",
                notes: "",
              }}
              validationSchema={organizationCreateValidationSchema}
              onSubmit={async (values, { resetForm, setStatus }) => {
                try {
                  await createCrmOrganization({
                    name: values.name.trim(),
                    website: optionalText(values.website),
                    type: values.type || undefined,
                    sector: optionalText(values.sector),
                    location: optionalText(values.location),
                    size: optionalText(values.size),
                    notes: optionalText(values.notes),
                  });
                  await refreshOrganizations();
                  resetForm();
                  setShowCreateForm(false);
                } catch {
                  setStatus("Failed to create organization.");
                }
              }}
            >
              {({ isSubmitting, status }) => (
                <Form className="flex flex-col gap-2 rounded-12 border border-border-subtle p-3">
                  <Text as="p" mainUiAction text02>
                    Create Organization
                  </Text>

                  <div className="grid gap-2 md:grid-cols-2">
                    <InputTypeInField name="name" placeholder="Organization name" />
                    <InputTypeInField name="website" placeholder="Website URL" />
                    <InputSelectField name="type">
                      <InputSelect.Trigger placeholder="Type" />
                      <InputSelect.Content>
                        {ORGANIZATION_TYPES.map((typeOption) => (
                          <InputSelect.Item key={typeOption} value={typeOption}>
                            {typeOption.toUpperCase()}
                          </InputSelect.Item>
                        ))}
                      </InputSelect.Content>
                    </InputSelectField>
                    <InputTypeInField name="sector" placeholder="Sector" />
                    <InputTypeInField name="location" placeholder="Location" />
                    <InputTypeInField name="size" placeholder="Size" />
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
                      className="text-status-error-03"
                    >
                      {status}
                    </Text>
                  )}

                  <div className="flex justify-end">
                    <Button action primary type="submit" disabled={isSubmitting}>
                      {isSubmitting ? "Creating..." : "Create Organization"}
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
              placeholder="Search organizations"
              leftSearchIcon
            />
            <Text as="p" secondaryAction text03>
              {totalItems} total
            </Text>
          </div>

          {error && (
            <Text as="p" secondaryBody className="text-status-error-03">
              Failed to load CRM organizations.
            </Text>
          )}

          {isLoading ? (
            <Text as="p" secondaryBody text03>
              Loading organizations...
            </Text>
          ) : organizations.length === 0 ? (
            <Text as="p" secondaryBody text03>
              No organizations found.
            </Text>
          ) : (
            <div className="flex flex-col gap-2">
              {organizations.map((organization) => (
                <Link
                  key={organization.id}
                  href={`/app/crm/organizations/${organization.id}`}
                  className="rounded-08 border border-border-subtle p-3 hover:bg-background-tint-02"
                >
                  <Text as="p" mainUiAction text02>
                    {organization.name}
                  </Text>
                  <Text as="p" secondaryBody text03>
                    {organization.website || "No website"}
                  </Text>
                  <Text as="p" secondaryBody text03>
                    {organization.type?.toUpperCase() || "No type"}
                  </Text>
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
