"use client";

import { Form, Formik } from "formik";
import { useEffect, useMemo, useState } from "react";

import {
  createCrmContact,
  CrmContactSource,
  CrmContactStage,
  uploadContactProfilePicture,
} from "@/app/app/crm/crmService";
import useShareableUsers from "@/hooks/useShareableUsers";
import { toast } from "@opal/layouts";
import { useCrmSettings } from "@/lib/hooks/useCrmSettings";
import { useInvalidateCrmCache } from "@/lib/hooks/useInvalidateCrmCache";
import { useUser } from "@/providers/UserProvider";
import Button from "@/refresh-components/buttons/Button";
import InputComboBoxField from "@/refresh-components/form/InputComboBoxField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputImage from "@/refresh-components/inputs/InputImage";
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
} from "@/views/crm/crmOptions";
import OrganizationPicker from "@/views/crm/components/OrganizationPicker";

import { SvgUser } from "@opal/icons";

interface ContactCreateValues {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  title: string;
  status: CrmContactStage;
  category: string;
  party_affiliation: string;
  us_state: string;
  principal: string;
  owner_ids: string[];
  source: CrmContactSource | "";
  notes: string;
  linkedin_url: string;
  location: string;
  organization_id: string;
  organization_name: string;
}

interface CreateContactModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organizationId?: string;
  organizationName?: string;
  onSuccess: () => void;
}

export default function CreateContactModal({
  open,
  onOpenChange,
  organizationId,
  organizationName,
  onSuccess,
}: CreateContactModalProps) {
  const { user } = useUser();
  const { crmSettings } = useCrmSettings();
  const invalidateCrmCache = useInvalidateCrmCache();
  const { data: usersData } = useShareableUsers({ includeApiKeys: false });
  const [pendingProfilePictureFile, setPendingProfilePictureFile] =
    useState<File | null>(null);
  const [profilePicturePreviewUrl, setProfilePicturePreviewUrl] = useState<
    string | null
  >(null);

  useEffect(() => {
    if (!pendingProfilePictureFile) {
      setProfilePicturePreviewUrl(null);
      return;
    }

    const objectUrl = URL.createObjectURL(pendingProfilePictureFile);
    setProfilePicturePreviewUrl(objectUrl);
    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [pendingProfilePictureFile]);

  useEffect(() => {
    if (!open) {
      setPendingProfilePictureFile(null);
    }
  }, [open]);

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
        label: candidate.email,
      })),
    [usersData]
  );
  const initialOwnerIds = useMemo(() => (user?.id ? [user.id] : []), [user]);

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="md" height="fit">
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
            party_affiliation: "",
            us_state: "",
            principal: "",
            owner_ids: initialOwnerIds,
            source: "",
            notes: "",
            linkedin_url: "",
            location: "",
            organization_id: organizationId ?? "",
            organization_name: organizationName ?? "",
          }}
          validationSchema={contactValidationSchema}
          onSubmit={async (values, { setStatus }) => {
            if (values.organization_name.trim() && !values.organization_id) {
              setStatus(
                "Choose a valid organization from the list or clear the organization field."
              );
              return;
            }

            try {
              const createdContact = await createCrmContact({
                first_name: optionalText(values.first_name),
                last_name: optionalText(values.last_name),
                email: optionalText(values.email),
                phone: optionalText(values.phone),
                title: optionalText(values.title),
                status: values.status,
                category: optionalText(values.category),
                party_affiliation: optionalText(values.party_affiliation),
                us_state: optionalText(values.us_state),
                principal: optionalText(values.principal),
                owner_ids: values.owner_ids,
                source: values.source || undefined,
                notes: optionalText(values.notes),
                linkedin_url: optionalText(values.linkedin_url),
                location: optionalText(values.location),
                organization_id: values.organization_id || undefined,
              });
              if (pendingProfilePictureFile) {
                try {
                  await uploadContactProfilePicture(
                    createdContact.id,
                    pendingProfilePictureFile
                  );
                } catch (error) {
                  console.error(
                    "Failed to upload CRM contact profile picture:",
                    error
                  );
                  toast.warning(
                    "Contact created, but the profile picture could not be uploaded."
                  );
                }
              }
              await invalidateCrmCache();
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
                  <div className="flex flex-col items-center gap-2">
                    <InputImage
                      src={profilePicturePreviewUrl || undefined}
                      alt="Contact profile picture"
                      size={96}
                      onDrop={(file) => {
                        setPendingProfilePictureFile(file);
                      }}
                      onDropRejected={(reason) => {
                        toast.error(reason);
                      }}
                      onRemove={
                        pendingProfilePictureFile
                          ? () => {
                              setPendingProfilePictureFile(null);
                            }
                          : undefined
                      }
                    />
                    <Text as="p" secondaryBody text03 className="text-sm">
                      Profile Picture
                    </Text>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <InputTypeInField
                      name="first_name"
                      placeholder="First name"
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
                    <OrganizationPicker
                      selectedOrganizationId={values.organization_id || null}
                      inputValue={values.organization_name}
                      onInputChange={(nextOrganizationName) => {
                        setFieldValue("organization_name", nextOrganizationName);
                        if (values.organization_id) {
                          setFieldValue("organization_id", "");
                        }
                      }}
                      onOrganizationChange={(
                        nextOrganizationId,
                        nextOrganizationName
                      ) => {
                        setFieldValue(
                          "organization_id",
                          nextOrganizationId || ""
                        );
                        setFieldValue(
                          "organization_name",
                          nextOrganizationName
                        );
                      }}
                      placeholder="Organization"
                    />
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
                    <InputTypeInField
                      name="party_affiliation"
                      placeholder="Party Affiliation"
                    />
                    <InputTypeInField
                      name="us_state"
                      placeholder="US State (e.g. CA)"
                    />
                    <InputTypeInField
                      name="principal"
                      placeholder="Principal (e.g. Sen. Jane Smith)"
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
