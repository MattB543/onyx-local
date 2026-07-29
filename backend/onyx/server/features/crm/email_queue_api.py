from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_curator_or_admin_user
from onyx.configs.app_configs import EMAIL_CRM_CUSTOM_JOB_ID
from onyx.db.custom_jobs import (
    count_trigger_events_by_status,
    get_custom_job_enabled,
    list_trigger_events_with_runs,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import CustomJobTriggerEventStatus
from onyx.db.models import CustomJobRun, CustomJobTriggerEvent, User
from onyx.server.documents.models import PaginatedReturn
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/user/crm")

EmailQueueStatusFilter = Literal["pending", "failed", "processed"]

_STATUS_FILTER_MAP: dict[str, list[CustomJobTriggerEventStatus]] = {
    "pending": [
        CustomJobTriggerEventStatus.RECEIVED,
        CustomJobTriggerEventStatus.ENQUEUED,
    ],
    "failed": [CustomJobTriggerEventStatus.FAILED],
    "processed": [
        CustomJobTriggerEventStatus.CONSUMED,
        CustomJobTriggerEventStatus.DROPPED,
    ],
}


class EmailQueueItem(BaseModel):
    id: UUID
    status: CustomJobTriggerEventStatus
    created_at: datetime
    event_time: datetime | None
    from_email: str | None
    to_email: str | None
    subject: str | None
    run_status: str | None
    error_message: str | None
    document_id: str | None


class EmailQueueConfigStatus(BaseModel):
    # True when EMAIL_CRM_CUSTOM_JOB_ID is set AND is a valid UUID.
    configured: bool
    # True when EMAIL_CRM_CUSTOM_JOB_ID is set at all (even if invalid),
    # letting the UI distinguish "not set" from "set but not a valid UUID".
    env_value_set: bool
    job_exists: bool
    job_enabled: bool
    counts: dict[str, int]


def _get_email_crm_job_id() -> UUID | None:
    if not EMAIL_CRM_CUSTOM_JOB_ID:
        return None
    try:
        return UUID(EMAIL_CRM_CUSTOM_JOB_ID)
    except ValueError:
        return None


def _payload_str(payload: dict | None, key: str) -> str | None:
    if not payload:
        return None
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _serialize_event(
    event: CustomJobTriggerEvent,
    run: CustomJobRun | None,
) -> EmailQueueItem:
    payload = event.payload_json or {}
    return EmailQueueItem(
        id=event.id,
        status=event.status,
        created_at=event.created_at,
        event_time=event.event_time,
        from_email=_payload_str(payload, "from"),
        to_email=_payload_str(payload, "to"),
        subject=_payload_str(payload, "subject")
        or _payload_str(payload, "semantic_identifier"),
        run_status=run.status.value if run is not None else None,
        error_message=event.error_message
        or (run.error_message if run is not None else None),
        document_id=_payload_str(payload, "document_id") or event.source_event_id,
    )


@router.get("/email-queue")
def get_email_queue(
    status: EmailQueueStatusFilter | None = Query(
        None,
        description=(
            "Optional status filter: pending (received/enqueued), "
            "failed, or processed (consumed/dropped)."
        ),
    ),
    page_num: int = Query(0, ge=0, description="Page number (0-indexed)."),
    page_size: int = Query(25, ge=1, le=200, description="Items per page."),
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_curator_or_admin_user),
) -> PaginatedReturn[EmailQueueItem]:
    custom_job_id = _get_email_crm_job_id()
    if custom_job_id is None:
        # Not configured: the UI should rely on /email-queue/config-status
        # to render a callout; just return an empty page here.
        return PaginatedReturn(items=[], total_items=0)

    statuses = _STATUS_FILTER_MAP[status] if status is not None else None
    rows, total_items = list_trigger_events_with_runs(
        db_session=db_session,
        custom_job_id=custom_job_id,
        statuses=statuses,
        page_num=page_num,
        page_size=page_size,
    )
    return PaginatedReturn(
        items=[_serialize_event(event, run) for event, run in rows],
        total_items=total_items,
    )


@router.get("/email-queue/config-status")
def get_email_queue_config_status(
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_curator_or_admin_user),
) -> EmailQueueConfigStatus:
    env_value_set = bool(EMAIL_CRM_CUSTOM_JOB_ID)
    custom_job_id = _get_email_crm_job_id()
    if custom_job_id is None:
        return EmailQueueConfigStatus(
            configured=False,
            env_value_set=env_value_set,
            job_exists=False,
            job_enabled=False,
            counts={},
        )

    job_enabled = get_custom_job_enabled(db_session=db_session, job_id=custom_job_id)
    counts = count_trigger_events_by_status(
        db_session=db_session,
        custom_job_id=custom_job_id,
    )
    return EmailQueueConfigStatus(
        configured=True,
        env_value_set=env_value_set,
        job_exists=job_enabled is not None,
        job_enabled=bool(job_enabled),
        counts={status.value: count for status, count in counts.items()},
    )
