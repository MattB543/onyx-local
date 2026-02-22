"use client";

import { Form, Formik } from "formik";
import * as Yup from "yup";

import {
  createCrmOrganization,
  CrmOrganizationType,
} from "@/app/app/crm/crmService";
import Button from "@/refresh-components/buttons/Button";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";

import { SvgOrganization } from "@opal/icons";

const ORGANIZATION_TYPES: CrmOrganizationType[] = [
  "customer",
  "prospect",
  "partner",
  "vendor",
  "other",
];

const validationSchema = Yup.object().shape({
  name: Yup.string().trim().required("Organization name is required."),
  website: Yup.string().trim().optional(),
});

interface OrgCreateValues {
  name: string;
  website: string;
  type: CrmOrganizationType | "";
  sector: string;
  location: string;
  size: string;
  notes: string;
}

function optionalText(value: string): string | undefined {
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

interface CreateOrganizationModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

export default function CreateOrganizationModal({
  open,
  onOpenChange,
  onSuccess,
}: CreateOrganizationModalProps) {
  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="md-sm" height="fit">
        <Modal.Header
          icon={SvgOrganization}
          title="New Organization"
          onClose={() => onOpenChange(false)}
        />
        <Formik<OrgCreateValues>
          initialValues={{
            name: "",
            website: "",
            type: "",
            sector: "",
            location: "",
            size: "",
            notes: "",
          }}
          validationSchema={validationSchema}
          onSubmit={async (values, { setStatus }) => {
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
              onSuccess();
              onOpenChange(false);
            } catch {
              setStatus("Failed to create organization.");
            }
          }}
        >
          {({ isSubmitting, status }) => (
            <Form>
              <Modal.Body>
                <div className="flex w-full flex-col gap-3">
                  <div className="grid gap-3 md:grid-cols-2">
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
                        {ORGANIZATION_TYPES.map((t) => (
                          <InputSelect.Item key={t} value={t}>
                            {t.charAt(0).toUpperCase() + t.slice(1)}
                          </InputSelect.Item>
                        ))}
                      </InputSelect.Content>
                    </InputSelectField>
                    <InputTypeInField name="sector" placeholder="Sector" />
                    <InputTypeInField name="location" placeholder="Location" />
                    <InputTypeInField
                      name="size"
                      placeholder="Size (e.g. 51-200)"
                    />
                  </div>
                  <InputTextAreaField
                    name="notes"
                    placeholder="Notes"
                    rows={3}
                  />

                  {status && (
                    <Text
                      as="p"
                      secondaryBody
                      className="text-sm text-status-error-03"
                    >
                      {status}
                    </Text>
                  )}
                </div>
              </Modal.Body>
              <Modal.Footer>
                <Button
                  action
                  secondary
                  size="md"
                  type="button"
                  onClick={() => onOpenChange(false)}
                >
                  Cancel
                </Button>
                <Button
                  action
                  primary
                  size="md"
                  type="submit"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? "Creating..." : "Create Organization"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
