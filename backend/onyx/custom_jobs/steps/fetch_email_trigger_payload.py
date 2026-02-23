from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult
from onyx.db.models import CustomJobRun
from onyx.utils.logger import setup_logger

logger = setup_logger()

REQUIRED_PAYLOAD_FIELDS = [
    "document_id",
    "source",
    "semantic_identifier",
    "primary_owner_emails",
    "text",
]


def _to_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry.strip() for entry in value if isinstance(entry, str) and entry.strip()]


def _normalize_email_payload(payload: dict[str, Any]) -> dict[str, Any]:
    primary_owner_emails = _to_string_list(payload.get("primary_owner_emails"))
    secondary_owner_emails = _to_string_list(payload.get("secondary_owner_emails"))

    from_field = str(payload.get("from") or "").strip()
    if not from_field and primary_owner_emails:
        from_field = primary_owner_emails[0]

    to_field = str(payload.get("to") or "").strip()
    if not to_field and secondary_owner_emails:
        to_field = ", ".join(secondary_owner_emails)

    subject = str(payload.get("subject") or "").strip()
    if not subject:
        subject = str(payload.get("semantic_identifier") or "").strip()

    date = str(payload.get("date") or "").strip()
    if not date:
        date = str(payload.get("doc_updated_at") or "").strip()

    body = str(payload.get("body") or "").strip()
    if not body:
        body = str(payload.get("text") or "").strip()

    return {
        "document_id": payload.get("document_id"),
        "source": payload.get("source"),
        "semantic_identifier": payload.get("semantic_identifier"),
        "doc_updated_at": payload.get("doc_updated_at"),
        "primary_owner_emails": primary_owner_emails,
        "secondary_owner_emails": secondary_owner_emails,
        "text": str(payload.get("text") or ""),
        "from": from_field,
        "to": to_field,
        "subject": subject,
        "date": date,
        "body": body,
    }


class FetchEmailTriggerPayloadStep(BaseStep):
    step_key = "fetch_email_trigger_payload"

    def run(self, context: StepContext) -> StepResult:
        run = context.db_session.scalar(
            select(CustomJobRun)
            .where(CustomJobRun.id == context.run_id)
            .options(selectinload(CustomJobRun.trigger_event))
        )
        if run is None:
            logger.warning(
                "fetch_email_trigger_payload run_not_found run_id=%s",
                context.run_id,
            )
            return StepResult.skipped(reason="Run not found.")

        trigger_event = run.trigger_event
        if trigger_event is None:
            logger.info(
                "fetch_email_trigger_payload no_trigger_event run_id=%s",
                context.run_id,
            )
            return StepResult.skipped(reason="No trigger event associated with this run.")

        payload: dict[str, Any] | None = trigger_event.payload_json
        if not payload:
            logger.info(
                "fetch_email_trigger_payload empty_payload run_id=%s trigger_event_id=%s",
                context.run_id,
                trigger_event.id,
            )
            return StepResult.skipped(reason="Trigger event payload is empty.")

        missing_fields = [
            field for field in REQUIRED_PAYLOAD_FIELDS if field not in payload
        ]
        if missing_fields:
            logger.warning(
                "fetch_email_trigger_payload missing_fields run_id=%s "
                "trigger_event_id=%s missing=%s",
                context.run_id,
                trigger_event.id,
                missing_fields,
            )
            return StepResult.skipped(
                reason=f"Trigger event payload missing required fields: {missing_fields}"
            )

        logger.info(
            "fetch_email_trigger_payload success run_id=%s trigger_event_id=%s "
            "document_id=%s source=%s",
            context.run_id,
            trigger_event.id,
            payload["document_id"],
            payload["source"],
        )

        return StepResult.success(output_json=_normalize_email_payload(payload))
