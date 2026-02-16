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
import {
  CrmOrganizationType,
  patchCrmOrganization,
} from "@/app/app/crm/crmService";
import { useCrmOrganization } from "@/lib/hooks/useCrmOrganization";
import { useCrmInteractions } from "@/lib/hooks/useCrmInteractions";
import CrmNav from "@/refresh-pages/crm/CrmNav";

const INTERACTIONS_PAGE_SIZE = 25;
const ORGANIZATION_TYPES: CrmOrganizationType[] = [
  "customer",
  "prospect",
  "partner",
  "vendor",
  "other",
];

interface OrganizationEditValues {
  name: string;
  website: string;
  type: CrmOrganizationType | "";
  sector: string;
  location: string;
  size: string;
  notes: string;
}

const organizationEditValidationSchema = Yup.object().shape({
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

export default function CrmOrganizationDetailPage({
  organizationId,
}: CrmOrganizationDetailPageProps) {
  const router = useRouter();
  const [interactionsPageNum, setInteractionsPageNum] = useState(0);

  const { organization, isLoading, error, refreshOrganization } =
    useCrmOrganization(organizationId);
  const {
    interactions,
    totalItems: totalInteractions,
    isLoading: isLoadingInteractions,
    error: interactionsError,
  } = useCrmInteractions({
    organizationId,
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
          title={organization?.name || "CRM Organization"}
          description="Edit organization details and review interaction history."
          backButton
          onBack={() => router.back()}
        >
          <CrmNav />
        </SettingsLayouts.Header>

        <SettingsLayouts.Body>
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
              validationSchema={organizationEditValidationSchema}
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
                  setStatus("Organization saved.");
                } catch {
                  setStatus("Failed to update organization.");
                }
              }}
            >
              {({ isSubmitting, status }) => (
                <Form className="flex flex-col gap-2 rounded-12 border border-border-subtle p-3">
                  <Text as="p" mainUiAction text02>
                    Organization Details
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

                  <Link
                    href={`/app/crm/contacts?organization_id=${organization.id}`}
                    className="w-fit"
                  >
                    <Text as="p" secondaryBody className="text-action-link-02">
                      View contacts in this organization
                    </Text>
                  </Link>

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
                      {isSubmitting ? "Saving..." : "Save Organization"}
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
                  {interaction.contact_id && (
                    <Link
                      href={`/app/crm/contacts/${interaction.contact_id}`}
                      className="w-fit"
                    >
                      <Text as="p" secondaryBody className="text-action-link-02">
                        View contact
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
