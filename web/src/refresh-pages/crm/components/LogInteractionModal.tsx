"use client";

import { Form, Formik } from "formik";
import { useEffect, useMemo, useState } from "react";
import * as Yup from "yup";

import {
  createCrmInteraction,
  listCrmContacts,
  updateCrmInteraction,
  CrmInteractionType,
} from "@/app/app/crm/crmService";
import type {
  CrmAttendeeRole,
  CrmInteraction,
  CrmInteractionAttendeeInput,
} from "@/app/app/crm/crmService";
import useShareableUsers from "@/hooks/useShareableUsers";
import { useInvalidateCrmCache } from "@/lib/hooks/useInvalidateCrmCache";
import { cn } from "@/lib/utils";
import { useUser } from "@/providers/UserProvider";
import Button from "@/refresh-components/buttons/Button";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputMultiSelect, {
  InputMultiSelectOption,
} from "@/refresh-components/inputs/InputMultiSelect";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";

import { SvgPlusCircle } from "@opal/icons";

import {
  fromDatetimeLocalInputValue,
  toDatetimeLocalInputValue,
} from "./crmDateUtils";
import InteractionTypeIcon from "./InteractionTypeIcon";

const INTERACTION_TYPES: CrmInteractionType[] = [
  "note",
  "call",
  "email",
  "meeting",
  "event",
];

const validationSchema = Yup.object().shape({
  title: Yup.string().trim().required("Title is required."),
});

interface LogInteractionFormValues {
  title: string;
  summary: string;
  occurred_at: string;
  contact_attendee_ids: string[];
  user_attendee_ids: string[];
}

interface LogInteractionModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contactId?: string;
  organizationId?: string;
  onSuccess: () => void;
  // When provided, the modal operates in EDIT mode for this interaction.
  interaction?: CrmInteraction;
}

export default function LogInteractionModal({
  open,
  onOpenChange,
  contactId,
  organizationId,
  onSuccess,
  interaction,
}: LogInteractionModalProps) {
  const { user } = useUser();
  const invalidateCrmCache = useInvalidateCrmCache();
  const { data: usersData } = useShareableUsers({ includeApiKeys: false });
  const isEditMode = interaction != null;
  const [selectedType, setSelectedType] = useState<CrmInteractionType>(
    interaction?.type ?? "note"
  );
  const [contactOptions, setContactOptions] = useState<
    InputMultiSelectOption[]
  >([]);
  const [isLoadingContacts, setIsLoadingContacts] = useState(false);
  const [contactLoadError, setContactLoadError] = useState<string | null>(null);

  const userOptions = useMemo<InputMultiSelectOption[]>(
    () =>
      (usersData || []).map((candidate) => ({
        value: candidate.id,
        label: candidate.email,
      })),
    [usersData]
  );

  useEffect(() => {
    if (!open) {
      return;
    }

    let canceled = false;

    async function fetchAllContacts() {
      setIsLoadingContacts(true);
      setContactLoadError(null);

      try {
        const allOptions: InputMultiSelectOption[] = [];
        const pageSize = 200;
        let pageNum = 0;
        let totalItems = 0;

        do {
          const response = await listCrmContacts({
            page_num: pageNum,
            page_size: pageSize,
          });
          totalItems = response.total_items;

          for (const contact of response.items) {
            const fullName = contact.full_name?.trim();
            const composedName = `${contact.first_name} ${
              contact.last_name || ""
            }`.trim();
            allOptions.push({
              value: contact.id,
              label: fullName || composedName || contact.email || contact.id,
            });
          }

          if (response.items.length === 0) {
            break;
          }

          pageNum += 1;
        } while (allOptions.length < totalItems);

        if (canceled) {
          return;
        }

        setContactOptions(allOptions);
      } catch {
        if (canceled) {
          return;
        }
        setContactLoadError("Failed to load contacts for attendees.");
      } finally {
        if (!canceled) {
          setIsLoadingContacts(false);
        }
      }
    }

    void fetchAllContacts();

    return () => {
      canceled = true;
    };
  }, [open]);

  // Keep the (externally-managed) type picker in sync with the interaction
  // being edited whenever the modal is (re)opened.
  useEffect(() => {
    if (!open) {
      return;
    }
    setSelectedType(interaction?.type ?? "note");
  }, [open, interaction]);

  const initialContactAttendeeIds = useMemo<string[]>(() => {
    if (interaction) {
      return interaction.attendees
        .filter((attendee) => attendee.contact_id)
        .map((attendee) => attendee.contact_id as string);
    }
    return contactId ? [contactId] : [];
  }, [interaction, contactId]);

  const initialUserAttendeeIds = useMemo<string[]>(() => {
    if (interaction) {
      return interaction.attendees
        .filter((attendee) => attendee.user_id)
        .map((attendee) => attendee.user_id as string);
    }
    return user?.id ? [user.id] : [];
  }, [interaction, user?.id]);

  const initialOccurredAt = useMemo<string>(() => {
    if (interaction) {
      return toDatetimeLocalInputValue(interaction.occurred_at);
    }
    return toDatetimeLocalInputValue(new Date().toISOString());
  }, [interaction]);

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="sm" height="fit">
        <Modal.Header
          icon={SvgPlusCircle}
          title={isEditMode ? "Edit Interaction" : "Log Interaction"}
          onClose={() => onOpenChange(false)}
        />
        <Formik<LogInteractionFormValues>
          enableReinitialize
          initialValues={{
            title: interaction?.title ?? "",
            summary: interaction?.summary ?? "",
            occurred_at: initialOccurredAt,
            contact_attendee_ids: initialContactAttendeeIds,
            user_attendee_ids: initialUserAttendeeIds,
          }}
          validationSchema={validationSchema}
          onSubmit={async (values, { setStatus, resetForm }) => {
            // In edit mode, preserve the existing roles of unchanged members
            // (only NEW members default to 'attendee') and never auto-promote
            // the current editor to organizer. In create mode, the current
            // user is the organizer.
            const existingContactRoles = new Map<string, CrmAttendeeRole>();
            const existingUserRoles = new Map<string, CrmAttendeeRole>();
            if (isEditMode && interaction) {
              for (const attendee of interaction.attendees) {
                if (attendee.contact_id) {
                  existingContactRoles.set(attendee.contact_id, attendee.role);
                }
                if (attendee.user_id) {
                  existingUserRoles.set(attendee.user_id, attendee.role);
                }
              }
            }

            const attendees: CrmInteractionAttendeeInput[] = [
              ...values.contact_attendee_ids.map((attendeeContactId) => ({
                contact_id: attendeeContactId,
                role:
                  existingContactRoles.get(attendeeContactId) ??
                  ("attendee" as CrmAttendeeRole),
              })),
              ...values.user_attendee_ids.map((attendeeUserId) => ({
                user_id: attendeeUserId,
                role:
                  existingUserRoles.get(attendeeUserId) ??
                  (!isEditMode && attendeeUserId === user?.id
                    ? ("organizer" as CrmAttendeeRole)
                    : ("attendee" as CrmAttendeeRole)),
              })),
            ];

            const occurredAtIso = fromDatetimeLocalInputValue(
              values.occurred_at
            );

            try {
              if (isEditMode && interaction) {
                await updateCrmInteraction(interaction.id, {
                  type: selectedType,
                  title: values.title.trim(),
                  summary: values.summary.trim() || null,
                  occurred_at: occurredAtIso,
                  attendees,
                });
              } else {
                await createCrmInteraction({
                  type: selectedType,
                  title: values.title.trim(),
                  summary: values.summary.trim() || undefined,
                  contact_id: contactId || undefined,
                  organization_id: organizationId || undefined,
                  occurred_at: occurredAtIso ?? new Date().toISOString(),
                  attendees,
                });
              }
              await invalidateCrmCache();
              resetForm();
              onSuccess();
              onOpenChange(false);
            } catch {
              setStatus(
                isEditMode
                  ? "Failed to update interaction."
                  : "Failed to log interaction."
              );
            }
          }}
        >
          {({ isSubmitting, status, values, setFieldValue }) => (
            <Form>
              <Modal.Body>
                <div className="flex w-full flex-col gap-4">
                  <div>
                    <Text as="p" secondaryBody text03 className="mb-2 text-sm">
                      Type
                    </Text>
                    <div className="flex gap-2">
                      {INTERACTION_TYPES.map((type) => (
                        <button
                          key={type}
                          type="button"
                          onClick={() => setSelectedType(type)}
                          className={cn(
                            "flex flex-col items-center gap-1 rounded-lg border px-3 py-2 transition-colors",
                            selectedType === type
                              ? "border-action-link-02 bg-background-tint-02"
                              : "border-border-subtle hover:bg-background-tint-02"
                          )}
                        >
                          <InteractionTypeIcon type={type} size={18} />
                          <span className="text-sm capitalize">{type}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <InputTypeInField
                    name="title"
                    placeholder="Title (e.g. 'Call about renewal')"
                  />
                  <InputTextAreaField
                    name="summary"
                    placeholder="Summary / notes"
                    rows={4}
                  />
                  <div className="flex w-full flex-col gap-1">
                    <Text as="p" secondaryBody text03 className="text-sm">
                      Occurred at
                    </Text>
                    <input
                      type="datetime-local"
                      name="occurred_at"
                      value={values.occurred_at}
                      onChange={(e) =>
                        setFieldValue("occurred_at", e.target.value)
                      }
                      max={toDatetimeLocalInputValue(new Date().toISOString())}
                      className="rounded border border-border-subtle bg-background-tint-00 px-3 py-2 text-sm"
                    />
                  </div>
                  <div className="flex w-full flex-col gap-1">
                    <Text as="p" secondaryBody text03 className="text-sm">
                      Contact attendees
                    </Text>
                    <InputMultiSelect
                      value={values.contact_attendee_ids}
                      onChange={(nextContactIds) => {
                        setFieldValue("contact_attendee_ids", nextContactIds);
                      }}
                      options={contactOptions}
                      placeholder="Select contact attendee(s)"
                      disabled={isLoadingContacts}
                    />
                    {contactLoadError && (
                      <Text
                        as="p"
                        secondaryBody
                        className="text-sm text-status-error-03"
                      >
                        {contactLoadError}
                      </Text>
                    )}
                  </div>
                  <div className="flex w-full flex-col gap-1">
                    <Text as="p" secondaryBody text03 className="text-sm">
                      Onyx user attendees
                    </Text>
                    <InputMultiSelect
                      value={values.user_attendee_ids}
                      onChange={(nextUserIds) => {
                        setFieldValue("user_attendee_ids", nextUserIds);
                      }}
                      options={userOptions}
                      placeholder="Select user attendee(s)"
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
                  {isSubmitting
                    ? "Saving..."
                    : isEditMode
                      ? "Save Changes"
                      : "Log Interaction"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
