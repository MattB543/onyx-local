"use client";

import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";

import { CrmImportResult, importCrmCsv } from "@/app/app/crm/crmService";
import { useInvalidateCrmCache } from "@/lib/hooks/useInvalidateCrmCache";
import Button from "@/refresh-components/buttons/Button";
import { Modal } from "@opal/components";
import Text from "@/refresh-components/texts/Text";

import { SvgUploadCloud } from "@opal/icons";

interface ImportCsvModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultEntityType?: "organizations" | "contacts" | "interactions";
  onSuccess?: () => void;
}

export default function ImportCsvModal({
  open,
  onOpenChange,
  defaultEntityType = "contacts",
  onSuccess,
}: ImportCsvModalProps) {
  const invalidateCrmCache = useInvalidateCrmCache();

  const [entityType, setEntityType] = useState<
    "organizations" | "contacts" | "interactions"
  >(defaultEntityType);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CrmImportResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0] ?? null);
      setResult(null);
      setErrorMessage(null);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"] },
    multiple: false,
  });

  const resetState = useCallback(() => {
    setFile(null);
    setResult(null);
    setErrorMessage(null);
    setLoading(false);
  }, []);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        resetState();
        setEntityType(defaultEntityType);
      }
      onOpenChange(nextOpen);
    },
    [onOpenChange, resetState, defaultEntityType]
  );

  const handleImport = useCallback(
    async (dryRun: boolean) => {
      if (!file) return;
      setLoading(true);
      setResult(null);
      setErrorMessage(null);

      try {
        const importResult = await importCrmCsv(entityType, file, dryRun);
        setResult(importResult);

        if (!dryRun && (importResult.created > 0 || importResult.updated > 0)) {
          await invalidateCrmCache();
          onSuccess?.();
        }
      } catch (err) {
        setErrorMessage(
          err instanceof Error ? err.message : "An unexpected error occurred."
        );
      } finally {
        setLoading(false);
      }
    },
    [entityType, file, invalidateCrmCache, onSuccess]
  );

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <Modal open={open} onOpenChange={handleOpenChange}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={SvgUploadCloud}
          title="Import CSV"
          onClose={() => handleOpenChange(false)}
        />
        <Modal.Body>
          <div className="flex w-full flex-col gap-4">
            {/* Entity type selection */}
            <div className="flex flex-col gap-1">
              <Text as="p" secondaryBody text03 className="text-sm">
                Entity type
              </Text>
              <div className="flex items-center gap-4">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-text-05">
                  <input
                    type="radio"
                    name="entityType"
                    value="organizations"
                    checked={entityType === "organizations"}
                    onChange={() => {
                      setEntityType("organizations");
                      setResult(null);
                      setErrorMessage(null);
                    }}
                    className="accent-brand-500"
                  />
                  Organizations
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm text-text-05">
                  <input
                    type="radio"
                    name="entityType"
                    value="contacts"
                    checked={entityType === "contacts"}
                    onChange={() => {
                      setEntityType("contacts");
                      setResult(null);
                      setErrorMessage(null);
                    }}
                    className="accent-brand-500"
                  />
                  Contacts
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm text-text-05">
                  <input
                    type="radio"
                    name="entityType"
                    value="interactions"
                    checked={entityType === "interactions"}
                    onChange={() => {
                      setEntityType("interactions");
                      setResult(null);
                      setErrorMessage(null);
                    }}
                    className="accent-brand-500"
                  />
                  Interactions
                </label>
              </div>
            </div>

            {/* Dropzone */}
            <div
              {...getRootProps()}
              className={`flex min-h-[120px] cursor-pointer flex-col items-center justify-center rounded-12 border-2 border-dashed p-4 transition-colors ${
                isDragActive
                  ? "border-brand-500 bg-background-tint-02"
                  : "border-border-02 hover:border-border-03"
              }`}
            >
              <input {...getInputProps()} />
              {file ? (
                <div className="flex flex-col items-center gap-1">
                  <Text
                    as="p"
                    secondaryBody
                    text05
                    className="text-sm font-medium"
                  >
                    {file.name}
                  </Text>
                  <Text as="p" secondaryBody text03 className="text-xs">
                    {formatFileSize(file.size)}
                  </Text>
                </div>
              ) : (
                <Text as="p" secondaryBody text03 className="text-sm">
                  Drop CSV file here or click to browse
                </Text>
              )}
            </div>

            {/* Error message */}
            {errorMessage && (
              <Text
                as="p"
                secondaryBody
                className="text-sm text-status-error-03"
              >
                {errorMessage}
              </Text>
            )}

            {/* Result display */}
            {result && (
              <div className="flex flex-col gap-2 rounded-08 border p-3">
                <div className="flex items-center gap-4">
                  <Text as="span" secondaryBody className="text-sm">
                    Created: {result.created}
                  </Text>
                  <Text as="span" secondaryBody className="text-sm">
                    Updated: {result.updated}
                  </Text>
                  <Text as="span" secondaryBody className="text-sm">
                    Skipped: {result.skipped}
                  </Text>
                </div>
                {result.errors.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <Text
                      as="p"
                      secondaryBody
                      className="text-sm font-medium text-status-error-03"
                    >
                      {result.errors.length} error
                      {result.errors.length !== 1 ? "s" : ""}:
                    </Text>
                    <div className="max-h-[160px] overflow-y-auto rounded-08 bg-background-tint-01 p-2">
                      {result.errors.map((err, idx) => (
                        <Text
                          key={idx}
                          as="p"
                          secondaryBody
                          className="text-xs text-status-error-03"
                        >
                          Row {err.row}: {err.error}
                        </Text>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button
            action
            secondary
            size="md"
            type="button"
            onClick={() => handleOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            action
            secondary
            size="md"
            type="button"
            disabled={!file || loading}
            onClick={() => handleImport(true)}
          >
            {loading ? "Validating..." : "Dry Run"}
          </Button>
          <Button
            action
            primary
            size="md"
            type="button"
            disabled={!file || loading}
            onClick={() => handleImport(false)}
          >
            {loading ? "Importing..." : "Import"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
