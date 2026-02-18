"use client";

import { Form, Formik } from "formik";
import { useState } from "react";
import * as Yup from "yup";

import { createCrmInteraction, CrmInteractionType } from "@/app/app/crm/crmService";
import { cn } from "@/lib/utils";
import Button from "@/refresh-components/buttons/Button";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";

import { SvgPlusCircle } from "@opal/icons";

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
}

interface LogInteractionModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contactId?: string;
  organizationId?: string;
  onSuccess: () => void;
}

export default function LogInteractionModal({
  open,
  onOpenChange,
  contactId,
  organizationId,
  onSuccess,
}: LogInteractionModalProps) {
  const [selectedType, setSelectedType] = useState<CrmInteractionType>("note");

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="sm" height="fit">
        <Modal.Header
          icon={SvgPlusCircle}
          title="Log Interaction"
          onClose={() => onOpenChange(false)}
        />
        <Formik<LogInteractionFormValues>
          initialValues={{
            title: "",
            summary: "",
          }}
          validationSchema={validationSchema}
          onSubmit={async (values, { setStatus }) => {
            try {
              await createCrmInteraction({
                type: selectedType,
                title: values.title.trim(),
                summary: values.summary.trim() || undefined,
                contact_id: contactId || undefined,
                organization_id: organizationId || undefined,
                occurred_at: new Date().toISOString(),
              });
              onSuccess();
              onOpenChange(false);
            } catch {
              setStatus("Failed to log interaction.");
            }
          }}
        >
          {({ isSubmitting, status }) => (
            <Form>
              <Modal.Body>
                <div className="flex w-full flex-col gap-4">
                  <div>
                    <Text as="p" secondaryBody text03 className="mb-2">
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
                          <span className="text-xs capitalize">{type}</span>
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
                  {isSubmitting ? "Saving..." : "Log Interaction"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
