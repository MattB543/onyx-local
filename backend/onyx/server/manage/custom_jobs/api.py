from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Response
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import ENABLE_CUSTOM_JOBS
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.custom_jobs.registry import build_workflow_definition
from onyx.custom_jobs.registry import get_step_catalog
from onyx.custom_jobs.registry import list_workflow_keys
from onyx.custom_jobs.registry import STEP_CONFIG_SCHEMAS
from onyx.custom_jobs.types import WorkflowDefinition
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.custom_jobs import add_custom_job_audit_log
from onyx.db.custom_jobs import compute_next_run_at
from onyx.db.custom_jobs import create_manual_run_if_allowed
from onyx.db.custom_jobs import fetch_custom_job
from onyx.db.custom_jobs import list_custom_job_runs
from onyx.db.custom_jobs import list_custom_job_run_steps
from onyx.db.custom_jobs import list_custom_jobs
from onyx.db.custom_jobs import RunListFilters
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import CustomJobRunStatus
from onyx.db.enums import CustomJobTriggerType
from onyx.db.models import CustomJob
from onyx.db.models import CustomJobRun
from onyx.db.models import User
from onyx.db.slack_bot import fetch_slack_bot
from onyx.server.manage.custom_jobs.models import (
    CustomJobCreateRequest,
)
from onyx.server.manage.custom_jobs.models import (
    CustomJobDryRunResponse,
)
from onyx.server.manage.custom_jobs.models import (
    CustomJobManualTriggerResponse,
)
from onyx.server.manage.custom_jobs.models import (
    CustomJobRunStepView,
)
from onyx.server.manage.custom_jobs.models import (
    CustomJobRunView,
)
from onyx.server.manage.custom_jobs.models import (
    CustomJobStepCatalogItem,
)
from onyx.server.manage.custom_jobs.models import (
    CustomJobUpdateRequest,
)
from onyx.server.manage.custom_jobs.models import (
    CustomJobView,
)
from onyx.server.manage.custom_jobs.models import (
    PaginatedCustomJobRuns,
)
from onyx.server.manage.custom_jobs.models import (
    PaginatedCustomJobRunSteps,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/custom-jobs")

_ALLOWED_RUN_SORTS = {"-started_at", "started_at", "-created_at", "created_at"}


def _ensure_custom_jobs_enabled() -> None:
    if not ENABLE_CUSTOM_JOBS:
        raise HTTPException(
            status_code=400,
            detail="Custom jobs are disabled. Set ENABLE_CUSTOM_JOBS=true to enable.",
        )


def _validate_schedule_fields(
    *,
    trigger_type: CustomJobTriggerType,
    timezone_name: str | None,
    hour: int | None,
    minute: int | None,
    day_of_week: int | None,
) -> None:
    if trigger_type == CustomJobTriggerType.TRIGGERED:
        return

    if timezone_name is None or hour is None or minute is None:
        raise HTTPException(
            status_code=400,
            detail="timezone/hour/minute are required for daily and weekly jobs.",
        )

    if hour < 0 or hour > 23:
        raise HTTPException(status_code=400, detail="hour must be between 0 and 23.")
    if minute < 0 or minute > 59:
        raise HTTPException(status_code=400, detail="minute must be between 0 and 59.")

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {timezone_name}") from e

    if trigger_type == CustomJobTriggerType.WEEKLY and (
        day_of_week is None or day_of_week < 0 or day_of_week > 6
    ):
        raise HTTPException(
            status_code=400,
            detail="day_of_week must be between 0 and 6 for weekly jobs (0=Monday).",
        )


def _validate_trigger_source_config(
    *,
    trigger_type: CustomJobTriggerType,
    trigger_source_config: dict[str, Any] | None,
) -> None:
    if trigger_type != CustomJobTriggerType.TRIGGERED or trigger_source_config is None:
        return

    poll_interval_seconds = trigger_source_config.get("poll_interval_seconds")
    if poll_interval_seconds is not None and (
        not isinstance(poll_interval_seconds, int) or poll_interval_seconds < 60
    ):
        raise HTTPException(
            status_code=400,
            detail="trigger_source_config.poll_interval_seconds must be an integer >= 60.",
        )

    max_events_per_claim = trigger_source_config.get("max_events_per_claim")
    if max_events_per_claim is not None and (
        not isinstance(max_events_per_claim, int) or max_events_per_claim < 1
    ):
        raise HTTPException(
            status_code=400,
            detail="trigger_source_config.max_events_per_claim must be an integer >= 1.",
        )

    max_concurrent_runs = trigger_source_config.get("max_concurrent_runs")
    if max_concurrent_runs is not None and (
        not isinstance(max_concurrent_runs, int) or max_concurrent_runs < 1
    ):
        raise HTTPException(
            status_code=400,
            detail="trigger_source_config.max_concurrent_runs must be an integer >= 1.",
        )


def _log_api_event(
    *,
    event: str,
    tenant_id: str,
    user_id: UUID | None,
    job_id: UUID | None = None,
    run_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "custom_job_api_event event=%s tenant_id=%s user_id=%s job_id=%s run_id=%s details=%s",
        event,
        tenant_id,
        str(user_id) if user_id else None,
        str(job_id) if job_id else None,
        str(run_id) if run_id else None,
        details or {},
    )


def _validate_workflow_and_step_configs(
    *,
    workflow_key: str,
    job_config: dict[str, Any],
) -> WorkflowDefinition:
    if workflow_key not in list_workflow_keys():
        raise HTTPException(status_code=400, detail=f"Unknown workflow_key: {workflow_key}")

    try:
        workflow = build_workflow_definition(
            workflow_key=workflow_key,
            job_config=job_config,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to build workflow definition: {e}",
        ) from e

    for step in workflow.steps:
        schema = STEP_CONFIG_SCHEMAS.get(step.step_key)
        if schema is None:
            continue
        try:
            jsonschema_validate(step.config or {}, schema)
        except JsonSchemaValidationError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid config for step '{step.step_id}': {e.message}",
            ) from e

    return workflow


def _resolve_next_run_at(
    *,
    enabled: bool,
    trigger_type: CustomJobTriggerType,
    timezone_name: str | None,
    hour: int | None,
    minute: int | None,
    day_of_week: int | None,
) -> datetime | None:
    if not enabled:
        return None
    return compute_next_run_at(
        trigger_type=trigger_type,
        timezone_name=timezone_name,
        hour=hour,
        minute=minute,
        day_of_week=day_of_week,
    )


def _dry_run_integration_checks(
    *,
    db_session: Session,
    workflow: WorkflowDefinition,
    job: CustomJob,
) -> list[str]:
    errors: list[str] = []

    for step in workflow.steps:
        step_config = step.config or {}

        if step.step_key in {"post_slack_digest", "slack_channel_input"}:
            slack_bot_id = (
                step_config.get("slack_bot_id")
                or job.slack_bot_id
                or (job.job_config or {}).get("slack_bot_id")
            )
            if not slack_bot_id:
                errors.append(
                    f"{step.step_id}: missing slack_bot_id in step or job config."
                )
            else:
                try:
                    slack_bot = fetch_slack_bot(db_session, int(slack_bot_id))
                    if slack_bot.bot_token is None or not slack_bot.bot_token.get_value(
                        apply_mask=False
                    ):
                        errors.append(f"{step.step_id}: slack bot token is empty.")
                except Exception as e:
                    errors.append(f"{step.step_id}: slack bot validation failed: {e}")

            if step.step_key == "post_slack_digest":
                channel_id = (
                    step_config.get("channel_id")
                    or job.slack_channel_id
                    or (job.job_config or {}).get("slack_channel_id")
                )
                if not channel_id:
                    errors.append(
                        f"{step.step_id}: missing channel_id in step or job config."
                    )

        if step.step_key == "google_doc_output":
            credential_id = step_config.get("credential_id") or (
                (job.job_config or {}).get("google_drive_credential_id")
            )
            if not credential_id:
                errors.append(
                    f"{step.step_id}: missing credential_id or google_drive_credential_id."
                )
            else:
                credential = fetch_credential_by_id(int(credential_id), db_session)
                if credential is None:
                    errors.append(
                        f"{step.step_id}: credential {credential_id} was not found."
                    )
                else:
                    if credential.source != DocumentSource.GOOGLE_DRIVE:
                        errors.append(
                            f"{step.step_id}: credential {credential_id} source must be GOOGLE_DRIVE."
                        )
                    if credential.credential_json is None:
                        errors.append(
                            f"{step.step_id}: credential {credential_id} has empty credential_json."
                        )

    return errors


@admin_router.get("/step-catalog", response_model=list[CustomJobStepCatalogItem])
def get_custom_job_step_catalog(
    _: User = Depends(current_admin_user),
) -> list[CustomJobStepCatalogItem]:
    _ensure_custom_jobs_enabled()
    return [CustomJobStepCatalogItem(**item) for item in get_step_catalog()]


@admin_router.get("/", response_model=list[CustomJobView])
def list_custom_jobs_endpoint(
    enabled: bool | None = Query(default=None),
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[CustomJobView]:
    _ensure_custom_jobs_enabled()
    jobs = list_custom_jobs(db_session=db_session, enabled=enabled)
    return [CustomJobView.from_model(job) for job in jobs]


@admin_router.post("/", response_model=CustomJobView)
def create_custom_job_endpoint(
    request: CustomJobCreateRequest,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomJobView:
    _ensure_custom_jobs_enabled()
    day_of_week = request.day_of_week
    hour = request.hour
    minute = request.minute
    timezone_name = request.timezone

    if request.trigger_type == CustomJobTriggerType.TRIGGERED:
        day_of_week = None
        hour = None
        minute = None
        timezone_name = None

    _validate_schedule_fields(
        trigger_type=request.trigger_type,
        timezone_name=timezone_name,
        hour=hour,
        minute=minute,
        day_of_week=day_of_week,
    )
    _validate_trigger_source_config(
        trigger_type=request.trigger_type,
        trigger_source_config=request.trigger_source_config,
    )
    _validate_workflow_and_step_configs(
        workflow_key=request.workflow_key,
        job_config=request.job_config or {},
    )

    next_run_at = _resolve_next_run_at(
        enabled=request.enabled,
        trigger_type=request.trigger_type,
        timezone_name=timezone_name,
        hour=hour,
        minute=minute,
        day_of_week=day_of_week,
    )

    job = CustomJob(
        name=request.name,
        workflow_key=request.workflow_key,
        enabled=request.enabled,
        trigger_type=request.trigger_type,
        day_of_week=day_of_week,
        hour=hour,
        minute=minute,
        timezone=timezone_name,
        next_run_at=next_run_at,
        trigger_source_type=request.trigger_source_type,
        trigger_source_config=request.trigger_source_config,
        job_config=request.job_config or {},
        persona_id=request.persona_id,
        slack_bot_id=request.slack_bot_id,
        slack_channel_id=request.slack_channel_id,
        retention_days=request.retention_days,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(job)
    db_session.flush()

    add_custom_job_audit_log(
        db_session=db_session,
        custom_job_id=job.id,
        action="CREATED",
        user_id=user.id,
        details_json={"workflow_key": request.workflow_key},
    )
    db_session.commit()
    db_session.refresh(job)
    _log_api_event(
        event="created",
        tenant_id=get_current_tenant_id(),
        user_id=user.id,
        job_id=job.id,
        details={"workflow_key": request.workflow_key},
    )
    return CustomJobView.from_model(job)


@admin_router.get("/{job_id}", response_model=CustomJobView)
def get_custom_job_endpoint(
    job_id: UUID,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomJobView:
    _ensure_custom_jobs_enabled()
    job = fetch_custom_job(db_session=db_session, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Custom job not found.")
    return CustomJobView.from_model(job)


@admin_router.patch("/{job_id}", response_model=CustomJobView)
def update_custom_job_endpoint(
    job_id: UUID,
    request: CustomJobUpdateRequest,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomJobView:
    _ensure_custom_jobs_enabled()
    job = fetch_custom_job(db_session=db_session, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Custom job not found.")

    updates = request.model_dump(exclude_unset=True)
    if not updates:
        return CustomJobView.from_model(job)

    if "name" in updates and updates["name"] is None:
        raise HTTPException(status_code=400, detail="name cannot be null.")
    if "workflow_key" in updates and updates["workflow_key"] is None:
        raise HTTPException(status_code=400, detail="workflow_key cannot be null.")
    if "job_config" in updates and updates["job_config"] is None:
        raise HTTPException(status_code=400, detail="job_config cannot be null.")
    if "retention_days" in updates and updates["retention_days"] is None:
        raise HTTPException(status_code=400, detail="retention_days cannot be null.")
    if "enabled" in updates and updates["enabled"] is None:
        raise HTTPException(status_code=400, detail="enabled cannot be null.")
    if "trigger_type" in updates and updates["trigger_type"] is None:
        raise HTTPException(status_code=400, detail="trigger_type cannot be null.")

    workflow_key = str(updates.get("workflow_key", job.workflow_key))
    job_config = updates.get("job_config", job.job_config or {})

    trigger_type = CustomJobTriggerType(
        updates.get("trigger_type", job.trigger_type)
    )
    enabled = bool(updates["enabled"]) if "enabled" in updates else job.enabled

    day_of_week = updates.get("day_of_week", job.day_of_week)
    hour = updates.get("hour", job.hour)
    minute = updates.get("minute", job.minute)
    timezone_name = updates.get("timezone", job.timezone)

    if trigger_type == CustomJobTriggerType.TRIGGERED:
        day_of_week = None
        hour = None
        minute = None
        timezone_name = None

    _validate_schedule_fields(
        trigger_type=trigger_type,
        timezone_name=timezone_name,
        hour=hour,
        minute=minute,
        day_of_week=day_of_week,
    )
    _validate_trigger_source_config(
        trigger_type=trigger_type,
        trigger_source_config=updates.get("trigger_source_config", job.trigger_source_config),
    )
    _validate_workflow_and_step_configs(
        workflow_key=workflow_key,
        job_config=job_config or {},
    )

    for field, value in updates.items():
        setattr(job, field, value)

    job.trigger_type = trigger_type
    job.day_of_week = day_of_week
    job.hour = hour
    job.minute = minute
    job.timezone = timezone_name
    job.enabled = enabled
    job.next_run_at = _resolve_next_run_at(
        enabled=enabled,
        trigger_type=trigger_type,
        timezone_name=timezone_name,
        hour=hour,
        minute=minute,
        day_of_week=day_of_week,
    )
    job.updated_by = user.id

    add_custom_job_audit_log(
        db_session=db_session,
        custom_job_id=job.id,
        action="UPDATED",
        user_id=user.id,
        details_json={"fields": sorted(updates.keys())},
    )

    db_session.commit()
    db_session.refresh(job)
    _log_api_event(
        event="updated",
        tenant_id=get_current_tenant_id(),
        user_id=user.id,
        job_id=job.id,
        details={"fields": sorted(updates.keys())},
    )
    return CustomJobView.from_model(job)


@admin_router.delete("/{job_id}", status_code=204, response_class=Response)
def delete_custom_job_endpoint(
    job_id: UUID,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> Response:
    _ensure_custom_jobs_enabled()
    job = fetch_custom_job(db_session=db_session, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Custom job not found.")
    deleted_job_id = job.id
    db_session.delete(job)
    db_session.commit()
    _log_api_event(
        event="deleted",
        tenant_id=get_current_tenant_id(),
        user_id=user.id,
        job_id=deleted_job_id,
    )
    return Response(status_code=204)


@admin_router.get("/{job_id}/runs", response_model=PaginatedCustomJobRuns)
def list_custom_job_runs_endpoint(
    job_id: UUID,
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=20, ge=1, le=200),
    status: CustomJobRunStatus | None = Query(default=None),
    started_after: datetime | None = Query(default=None),
    started_before: datetime | None = Query(default=None),
    sort: str = Query(default="-started_at"),
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedCustomJobRuns:
    _ensure_custom_jobs_enabled()
    if sort not in _ALLOWED_RUN_SORTS:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")

    job = fetch_custom_job(db_session=db_session, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Custom job not found.")

    filters = RunListFilters(
        status=status,
        started_after=started_after,
        started_before=started_before,
        sort=sort,
    )
    runs, total = list_custom_job_runs(
        db_session=db_session,
        job_id=job_id,
        page=page,
        page_size=page_size,
        filters=filters,
    )
    return PaginatedCustomJobRuns(
        items=[CustomJobRunView.from_model(run) for run in runs],
        total_items=total,
    )


@admin_router.get(
    "/{job_id}/runs/{run_id}/steps",
    response_model=PaginatedCustomJobRunSteps,
)
def list_custom_job_run_steps_endpoint(
    job_id: UUID,
    run_id: UUID,
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=50, ge=1, le=500),
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> PaginatedCustomJobRunSteps:
    _ensure_custom_jobs_enabled()
    run = db_session.scalar(
        select(CustomJobRun).where(
            CustomJobRun.id == run_id, CustomJobRun.custom_job_id == job_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found for this job.")

    steps, total = list_custom_job_run_steps(
        db_session=db_session,
        run_id=run_id,
        page=page,
        page_size=page_size,
    )
    return PaginatedCustomJobRunSteps(
        items=[CustomJobRunStepView.from_model(step) for step in steps],
        total_items=total,
    )


@admin_router.post("/{job_id}/trigger", response_model=CustomJobManualTriggerResponse)
def manual_trigger_custom_job_endpoint(
    job_id: UUID,
    idempotency_key: str | None = Query(default=None, min_length=1, max_length=255),
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomJobManualTriggerResponse:
    _ensure_custom_jobs_enabled()
    job = fetch_custom_job(db_session=db_session, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Custom job not found.")
    if not job.enabled:
        raise HTTPException(status_code=400, detail="Custom job is disabled.")

    normalized_idempotency_key = idempotency_key.strip() if idempotency_key else None
    try:
        manual_result = create_manual_run_if_allowed(
            db_session=db_session,
            job=job,
            idempotency_key=normalized_idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    run = manual_result.run

    add_custom_job_audit_log(
        db_session=db_session,
        custom_job_id=job.id,
        action="TRIGGERED",
        user_id=user.id,
        details_json={
            "run_id": str(run.id),
            "mode": "manual",
            "deduplicated": not manual_result.created,
            "idempotency_key": normalized_idempotency_key,
        },
    )
    db_session.commit()

    if not manual_result.created:
        _log_api_event(
            event="manual_trigger_deduplicated",
            tenant_id=get_current_tenant_id(),
            user_id=user.id,
            job_id=job.id,
            run_id=run.id,
            details={
                "idempotency_key": normalized_idempotency_key,
                "run_status": run.status.value,
            },
        )
        return CustomJobManualTriggerResponse(run_id=run.id, status="deduplicated")

    try:
        client_app.send_task(
            OnyxCeleryTask.RUN_CUSTOM_JOB,
            kwargs={
                "run_id": str(run.id),
                "tenant_id": get_current_tenant_id(),
            },
            queue=OnyxCeleryQueues.CSV_GENERATION,
            priority=OnyxCeleryPriority.MEDIUM,
        )
    except Exception as e:
        failed_run = db_session.scalar(
            select(CustomJobRun).where(CustomJobRun.id == run.id)
        )
        if failed_run is not None:
            failed_run.status = CustomJobRunStatus.FAILURE
            failed_run.error_message = f"Failed to enqueue custom job run: {e}"
            failed_run.finished_at = datetime.now(timezone.utc)
            db_session.commit()
        _log_api_event(
            event="manual_trigger_enqueue_failed",
            tenant_id=get_current_tenant_id(),
            user_id=user.id,
            job_id=job.id,
            run_id=run.id,
            details={"error": str(e)},
        )
        raise HTTPException(
            status_code=500, detail=f"Unable to enqueue manual run: {e}"
        ) from e

    _log_api_event(
        event="manual_trigger_queued",
        tenant_id=get_current_tenant_id(),
        user_id=user.id,
        job_id=job.id,
        run_id=run.id,
        details={"idempotency_key": normalized_idempotency_key},
    )
    return CustomJobManualTriggerResponse(run_id=run.id, status="queued")


@admin_router.post("/{job_id}/dry-run", response_model=CustomJobDryRunResponse)
def dry_run_custom_job_endpoint(
    job_id: UUID,
    user: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomJobDryRunResponse:
    _ensure_custom_jobs_enabled()
    job = fetch_custom_job(db_session=db_session, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Custom job not found.")

    errors: list[str] = []
    warnings: list[str] = []
    workflow: WorkflowDefinition | None = None

    try:
        _validate_schedule_fields(
            trigger_type=job.trigger_type,
            timezone_name=job.timezone,
            hour=job.hour,
            minute=job.minute,
            day_of_week=job.day_of_week,
        )
    except HTTPException as e:
        errors.append(str(e.detail))

    try:
        _validate_trigger_source_config(
            trigger_type=job.trigger_type,
            trigger_source_config=job.trigger_source_config,
        )
    except HTTPException as e:
        errors.append(str(e.detail))

    try:
        workflow = _validate_workflow_and_step_configs(
            workflow_key=job.workflow_key,
            job_config=job.job_config or {},
        )
    except HTTPException as e:
        errors.append(str(e.detail))

    if workflow is not None:
        errors.extend(
            _dry_run_integration_checks(
                db_session=db_session,
                workflow=workflow,
                job=job,
            )
        )

    if job.trigger_type == CustomJobTriggerType.TRIGGERED and (
        job.trigger_source_type is None
    ):
        warnings.append(
            "Triggered job has no trigger_source_type configured; poller will no-op."
        )

    _log_api_event(
        event="dry_run",
        tenant_id=get_current_tenant_id(),
        user_id=user.id,
        job_id=job.id,
        details={"valid": len(errors) == 0, "error_count": len(errors)},
    )
    return CustomJobDryRunResponse(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        step_count=len(workflow.steps) if workflow is not None else 0,
    )
