"use client";

import { Form, Formik } from "formik";
import * as Yup from "yup";

import { createCrmContact, CrmContactSource, CrmContactStatus } from "@/app/app/crm/crmService";
import Button from "@/refresh-components/buttons/Button";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";

import { SvgUser } from "@opal/icons";

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

const validationSchema = Yup.object().shape({
  first_name: Yup.string().trim().required("First name is required."),
  email: Yup.string().trim().email("Enter a valid email.").optional(),
});

interface ContactCreateValues {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  status: CrmContactStatus;
  source: CrmContactSource | "";
  notes: string;
  linkedin_url: string;
  location: string;
}

function optionalText(value: string): string | undefined {
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

interface CreateContactModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organizationId?: string;
  onSuccess: () => void;
}

export default function CreateContactModal({
  open,
  onOpenChange,
  organizationId,
  onSuccess,
}: CreateContactModalProps) {
  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="md-sm" height="fit">
        <Modal.Header
          icon={SvgUser}
          title="New Contact"
          onClose={() => onOpenChange(false)}
        />
        <Formik<ContactCreateValues>
          initialValues={{
            first_name: "",
            last_name: "",
            email: "",
            phone: "",
            title: "",
            status: "lead",
            source: "",
            notes: "",
            linkedin_url: "",
            location: "",
          }}
          validationSchema={validationSchema}
          onSubmit={async (values, { setStatus }) => {
            try {
              await createCrmContact({
                first_name: values.first_name.trim(),
                last_name: optionalText(values.last_name),
                email: optionalText(values.email),
                phone: optionalText(values.phone),
                title: optionalText(values.title),
                status: values.status,
                source: values.source || undefined,
                notes: optionalText(values.notes),
                linkedin_url: optionalText(values.linkedin_url),
                location: optionalText(values.location),
                organization_id: organizationId,
              });
              onSuccess();
              onOpenChange(false);
            } catch {
              setStatus("Failed to create contact.");
            }
          }}
        >
          {({ isSubmitting, status }) => (
            <Form>
              <Modal.Body>
                <div className="flex w-full flex-col gap-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <InputTypeInField
                      name="first_name"
                      placeholder="First name *"
                    />
                    <InputTypeInField
                      name="last_name"
                      placeholder="Last name"
                    />
                    <InputTypeInField name="email" placeholder="Email" />
                    <InputTypeInField name="phone" placeholder="Phone" />
                    <InputTypeInField
                      name="title"
                      placeholder="Title (e.g. VP of Engineering)"
                    />
                    <InputTypeInField name="location" placeholder="Location" />
                    <InputTypeInField
                      name="linkedin_url"
                      placeholder="LinkedIn URL"
                    />
                    <InputSelectField name="status">
                      <InputSelect.Trigger placeholder="Status" />
                      <InputSelect.Content>
                        {CONTACT_STATUSES.map((s) => (
                          <InputSelect.Item key={s} value={s}>
                            {s.charAt(0).toUpperCase() + s.slice(1)}
                          </InputSelect.Item>
                        ))}
                      </InputSelect.Content>
                    </InputSelectField>
                    <InputSelectField name="source">
                      <InputSelect.Trigger placeholder="Source" />
                      <InputSelect.Content>
                        {CONTACT_SOURCES.map((s) => (
                          <InputSelect.Item key={s} value={s}>
                            {s.charAt(0).toUpperCase() + s.slice(1)}
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
                    <Text as="p" secondaryBody className="text-status-error-03">
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
                  {isSubmitting ? "Creating..." : "Create Contact"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
