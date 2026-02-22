from __future__ import annotations

from datetime import datetime
from datetime import timezone

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.resources import get_drive_service
from onyx.connectors.google_utils.resources import get_google_docs_service
from onyx.connectors.google_utils.shared_constants import DB_CREDENTIALS_PRIMARY_ADMIN_KEY
from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult
from onyx.db.credentials import fetch_credential_by_id


class GoogleDocOutputStep(BaseStep):
    step_key = "google_doc_output"

    def run(self, context: StepContext) -> StepResult:
        input_step_id = context.step_config.get("input_step_id", "summarize_weekly_content")
        input_payload = context.previous_outputs.get(input_step_id)
        if input_payload is None:
            return StepResult.failure(f"Missing required step output: {input_step_id}")

        content = (input_payload.get("summary") or input_payload.get("content") or "").strip()
        if not content:
            return StepResult.skipped(
                output_json={"created": False, "reason": "empty_content"},
                reason="No content available for Google Doc output.",
            )

        credential_id = context.step_config.get("credential_id") or context.job_config.get(
            "google_drive_credential_id"
        )
        if not credential_id:
            return StepResult.failure("Missing Google Drive credential_id.")

        credential = fetch_credential_by_id(int(credential_id), context.db_session)
        if credential is None:
            return StepResult.failure(f"Credential {credential_id} was not found.")
        if credential.source != DocumentSource.GOOGLE_DRIVE:
            return StepResult.failure("Credential source must be GOOGLE_DRIVE.")
        if credential.credential_json is None:
            return StepResult.failure("Credential has empty credential_json.")

        credential_json = credential.credential_json.get_value(apply_mask=False)
        user_email = credential_json.get(DB_CREDENTIALS_PRIMARY_ADMIN_KEY)
        creds, _ = get_google_creds(
            credentials=credential_json,
            source=DocumentSource.GOOGLE_DRIVE,
        )

        docs_service = get_google_docs_service(creds=creds, user_email=user_email)
        drive_service = get_drive_service(creds=creds, user_email=user_email)

        title = context.step_config.get("title") or (
            "Onyx Job Output " + datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        folder_id = context.step_config.get("folder_id")
        share_with = context.step_config.get("share_with") or []

        try:
            doc = docs_service.documents().create(body={"title": title}).execute()
            doc_id = doc["documentId"]

            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": 1},
                                "text": content,
                            }
                        }
                    ]
                },
            ).execute()

            if folder_id:
                drive_service.files().update(
                    fileId=doc_id,
                    addParents=folder_id,
                    removeParents="root",
                    fields="id, webViewLink",
                ).execute()

            for email in share_with:
                drive_service.permissions().create(
                    fileId=doc_id,
                    body={"type": "user", "role": "writer", "emailAddress": email},
                    sendNotificationEmail=False,
                ).execute()

            file_meta = drive_service.files().get(
                fileId=doc_id, fields="id, webViewLink"
            ).execute()
        except Exception as e:
            return StepResult.failure(f"Google Doc output failed: {e}")

        return StepResult.success(
            output_json={
                "created": True,
                "doc_id": file_meta.get("id"),
                "doc_url": file_meta.get("webViewLink"),
                "title": title,
            }
        )
