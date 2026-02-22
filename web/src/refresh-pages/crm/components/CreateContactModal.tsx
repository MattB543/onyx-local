"use client";

import { Form, Formik } from "formik";
import { useMemo } from "react";

import {
  createCrmContact,
  CrmContactSource,
  CrmContactStage,
} from "@/app/app/crm/crmService";
import useShareableUsers from "@/hooks/useShareableUsers";
import { useCrmSettings } from "@/lib/hooks/useCrmSettings";
import { useUser } from "@/providers/UserProvider";
import Button from "@/refresh-components/buttons/Button";
import InputComboBoxField from "@/refresh-components/form/InputComboBoxField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputMultiSelect, {
  InputMultiSelectOption,
} from "@/refresh-components/inputs/InputMultiSelect";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import {
  CONTACT_SOURCES,
  contactValidationSchema,
  DEFAULT_CRM_CATEGORY_SUGGESTIONS,
  DEFAULT_CRM_STAGE_OPTIONS,
  formatCrmLabel,
  optionalText,
} from "@/refresh-pages/crm/crmOptions";

import { SvgUser } from "@opal/icons";

interface ContactCreateValues {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  status: CrmContactStage;
  category: string;
  owner_ids: string[];
  source: CrmContactSource | "";
  notes: string;
  linkedin_url: string;
  location: string;
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
  const { user } = useUser();
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
  const initialOwnerIds = useMemo(() => (user?.id ? [user.id] : []), [user]);

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="md-sm" height="fit">
        <Modal.Header
          icon={SvgUser}
          title="New Contact"
          onClose={() => onOpenChange(false)}
        />
        <Formik<ContactCreateValues>
          enableReinitialize
          initialValues={{
            first_name: "",
            last_name: "",
            email: "",
            phone: "",
            title: "",
            status: stageOptions[0] ?? "lead",
            category: "",
            owner_ids: initialOwnerIds,
            source: "",
            notes: "",
            linkedin_url: "",
            location: "",
          }}
          validationSchema={contactValidationSchema}
          onSubmit={async (values, { setStatus }) => {
            try {
              await createCrmContact({
                first_name: values.first_name.trim(),
                last_name: optionalText(values.last_name),
                email: optionalText(values.email),
                phone: optionalText(values.phone),
                title: optionalText(values.title),
                status: values.status,
                category: optionalText(values.category),
                owner_ids: values.owner_ids,
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
          {({ isSubmitting, status, values, setFieldValue }) => (
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
                        {stageOptions.map((s) => (
                          <InputSelect.Item key={s} value={s}>
                            {formatCrmLabel(s)}
                          </InputSelect.Item>
                        ))}
                      </InputSelect.Content>
                    </InputSelectField>
                    <InputSelectField name="source">
                      <InputSelect.Trigger placeholder="Source" />
                      <InputSelect.Content>
                        {CONTACT_SOURCES.map((s) => (
                          <InputSelect.Item key={s} value={s}>
                            {formatCrmLabel(s)}
                          </InputSelect.Item>
                        ))}
                      </InputSelect.Content>
                    </InputSelectField>
                    <InputComboBoxField
                      name="category"
                      options={categoryOptions}
                      strict={false}
                      placeholder="Category"
                    />
                  </div>
                  <div className="flex w-full flex-col gap-1">
                    <Text as="p" secondaryBody text03 className="text-sm">
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
