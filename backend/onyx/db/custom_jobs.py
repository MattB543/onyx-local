from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload
from zoneinfo import ZoneInfo

from onyx.db.enums import CustomJobRunStatus
from onyx.db.enums import CustomJobStepStatus
from onyx.db.enums import CustomJobTriggerEventStatus
from onyx.db.enums import CustomJobTriggerType
from onyx.db.models import CustomJob
from onyx.db.models import CustomJobAuditLog
from onyx.db.models import CustomJobRun
from onyx.db.models import CustomJobRunStep
from onyx.db.models import CustomJobTriggerEvent
from onyx.db.models import CustomJobTriggerState
from onyx.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_MANUAL_TRIGGER_COOLDOWN_SECONDS = 60
DEFAULT_CLAIM_LIMIT = 50
DEFAULT_STALE_MULTIPLIER = 2


@dataclass
class RunListFilters:
    status: CustomJobRunStatus | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None
    sort: str = "-started_at"


@dataclass
class ManualRunRequestResult:
    run: CustomJobRun
    created: bool


def _normalize_local_candidate(
    *,
    tz: ZoneInfo,
    naive_local: datetime,
) -> datetime:
    """Resolve DST edge cases for local schedule intent.

    - Ambiguous local times use first occurrence (`fold=0`).
    - Non-existent local times are shifted to the next valid minute.
    """
    candidate = naive_local.replace(tzinfo=tz, fold=0)
    roundtrip = candidate.astimezone(timezone.utc).astimezone(tz)
    if roundtrip.replace(second=0, microsecond=0, tzinfo=None) != naive_local:
        return roundtrip.replace(second=0, microsecond=0)
    return candidate


def _next_daily_run_local(
    *,
    now_local: datetime,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> datetime:
    target_date = now_local.date()
    candidate = _normalize_local_candidate(
        tz=tz,
        naive_local=datetime(
            target_date.year, target_date.month, target_date.day, hour, minute
        ),
    )
    if candidate <= now_local:
        next_day = target_date + timedelta(days=1)
        candidate = _normalize_local_candidate(
            tz=tz,
            naive_local=datetime(
                next_day.year, next_day.month, next_day.day, hour, minute
            ),
        )
    return candidate


def _next_weekly_run_local(
    *,
    now_local: datetime,
    day_of_week: int,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> datetime:
    if day_of_week < 0 or day_of_week > 6:
        raise ValueError("day_of_week must be between 0 and 6 (0=Monday)")

    current_day = now_local.weekday()
    days_ahead = (day_of_week - current_day) % 7
    target_date = now_local.date() + timedelta(days=days_ahead)
    candidate = _normalize_local_candidate(
        tz=tz,
        naive_local=datetime(
            target_date.year, target_date.month, target_date.day, hour, minute
        ),
    )
    if candidate <= now_local:
        target_date = target_date + timedelta(days=7)
        candidate = _normalize_local_candidate(
            tz=tz,
            naive_local=datetime(
                target_date.year, target_date.month, target_date.day, hour, minute
            ),
        )
    return candidate


def compute_next_run_at(
    *,
    trigger_type: CustomJobTriggerType,
    timezone_name: str | None,
    hour: int | None,
    minute: int | None,
    day_of_week: int | None,
    now_utc: datetime | None = None,
) -> datetime | None:
    if trigger_type == CustomJobTriggerType.TRIGGERED:
        return None

    if hour is None or minute is None or timezone_name is None:
        raise ValueError("timezone/hour/minute are required for scheduled jobs")

    if hour < 0 or hour > 23:
        raise ValueError("hour must be between 0 and 23")
    if minute < 0 or minute > 59:
        raise ValueError("minute must be between 0 and 59")

    tz = ZoneInfo(timezone_name)
    now_utc = now_utc or datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)

    if trigger_type == CustomJobTriggerType.DAILY:
        next_local = _next_daily_run_local(
            now_local=now_local, hour=hour, minute=minute, tz=tz
        )
    elif trigger_type == CustomJobTriggerType.WEEKLY:
        if day_of_week is None:
            raise ValueError("day_of_week is required for weekly jobs")
        next_local = _next_weekly_run_local(
            now_local=now_local,
            day_of_week=day_of_week,
            hour=hour,
            minute=minute,
            tz=tz,
        )
    else:
        raise ValueError(f"Unsupported trigger_type: {trigger_type}")

    return next_local.astimezone(timezone.utc)


def add_custom_job_audit_log(
    *,
    db_session: Session,
    custom_job_id: UUID,
    action: str,
    user_id: UUID | None,
    details_json: dict[str, Any] | None = None,
) -> None:
    db_session.add(
        CustomJobAuditLog(
            custom_job_id=custom_job_id,
            user_id=user_id,
            action=action,
            details_json=details_json,
        )
    )


def fetch_custom_job(
    *,
    db_session: Session,
    job_id: UUID,
) -> CustomJob | None:
    return db_session.scalar(
        select(CustomJob)
        .where(CustomJob.id == job_id)
        .options(selectinload(CustomJob.runs))
    )


def list_custom_jobs(
    *,
    db_session: Session,
    enabled: bool | None = None,
) -> list[CustomJob]:
    stmt = select(CustomJob).order_by(CustomJob.created_at.desc())
    if enabled is not None:
        stmt = stmt.where(CustomJob.enabled == enabled)
    return list(db_session.scalars(stmt).all())


def list_custom_job_runs(
    *,
    db_session: Session,
    job_id: UUID,
    page: int,
    page_size: int,
    filters: RunListFilters,
) -> tuple[list[CustomJobRun], int]:
    stmt = select(CustomJobRun).where(CustomJobRun.custom_job_id == job_id)
    count_stmt = select(func.count()).select_from(CustomJobRun).where(
        CustomJobRun.custom_job_id == job_id
    )

    if filters.status is not None:
        stmt = stmt.where(CustomJobRun.status == filters.status)
        count_stmt = count_stmt.where(CustomJobRun.status == filters.status)
    if filters.started_after is not None:
        stmt = stmt.where(CustomJobRun.started_at >= filters.started_after)
        count_stmt = count_stmt.where(CustomJobRun.started_at >= filters.started_after)
    if filters.started_before is not None:
        stmt = stmt.where(CustomJobRun.started_at <= filters.started_before)
        count_stmt = count_stmt.where(CustomJobRun.started_at <= filters.started_before)

    if filters.sort == "started_at":
        stmt = stmt.order_by(CustomJobRun.started_at.asc().nullsfirst())
    elif filters.sort == "-created_at":
        stmt = stmt.order_by(CustomJobRun.created_at.desc())
    elif filters.sort == "created_at":
        stmt = stmt.order_by(CustomJobRun.created_at.asc())
    else:
        stmt = stmt.order_by(CustomJobRun.started_at.desc().nullslast())

    runs = list(db_session.scalars(stmt.offset(page * page_size).limit(page_size)).all())
    total = db_session.scalar(count_stmt) or 0
    return runs, total


def list_custom_job_run_steps(
    *,
    db_session: Session,
    run_id: UUID,
    page: int,
    page_size: int,
) -> tuple[list[CustomJobRunStep], int]:
    stmt = (
        select(CustomJobRunStep)
        .where(CustomJobRunStep.run_id == run_id)
        .order_by(CustomJobRunStep.step_index.asc())
    )
    count_stmt = (
        select(func.count())
        .select_from(CustomJobRunStep)
        .where(CustomJobRunStep.run_id == run_id)
    )
    steps = list(db_session.scalars(stmt.offset(page * page_size).limit(page_size)).all())
    total = db_session.scalar(count_stmt) or 0
    return steps, total


def create_manual_run_if_allowed(
    *,
    db_session: Session,
    job: CustomJob,
    cooldown_seconds: int = DEFAULT_MANUAL_TRIGGER_COOLDOWN_SECONDS,
    idempotency_key: str | None = None,
) -> ManualRunRequestResult:
    normalized_idempotency_key = idempotency_key.strip() if idempotency_key else None
    now = datetime.now(timezone.utc)

    if normalized_idempotency_key:
        existing_run = db_session.scalar(
            select(CustomJobRun)
            .where(
                CustomJobRun.custom_job_id == job.id,
                CustomJobRun.idempotency_key == normalized_idempotency_key,
            )
            .order_by(CustomJobRun.created_at.desc())
            .limit(1)
        )
        if existing_run is not None:
            return ManualRunRequestResult(run=existing_run, created=False)

    recent_run = db_session.scalar(
        select(CustomJobRun)
        .where(CustomJobRun.custom_job_id == job.id)
        .order_by(CustomJobRun.created_at.desc())
        .limit(1)
    )
    if recent_run and recent_run.created_at >= now - timedelta(seconds=cooldown_seconds):
        raise ValueError(
            f"Manual trigger cooldown active ({cooldown_seconds}s). Try again later."
        )

    run = CustomJobRun(
        custom_job_id=job.id,
        status=CustomJobRunStatus.PENDING,
        scheduled_for=None,
        trigger_event_id=None,
        idempotency_key=normalized_idempotency_key,
    )
    try:
        with db_session.begin_nested():
            db_session.add(run)
            db_session.flush()
    except IntegrityError:
        if normalized_idempotency_key:
            deduped_run = db_session.scalar(
                select(CustomJobRun)
                .where(
                    CustomJobRun.custom_job_id == job.id,
                    CustomJobRun.idempotency_key == normalized_idempotency_key,
                )
                .order_by(CustomJobRun.created_at.desc())
                .limit(1)
            )
            if deduped_run is not None:
                return ManualRunRequestResult(run=deduped_run, created=False)
        raise

    return ManualRunRequestResult(run=run, created=True)


def mark_stale_started_runs_failed(
    *,
    db_session: Session,
    max_runtime_seconds: int,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=max_runtime_seconds * DEFAULT_STALE_MULTIPLIER
    )
    stale_runs = list(
        db_session.scalars(
            select(CustomJobRun).where(
                CustomJobRun.status == CustomJobRunStatus.STARTED,
                CustomJobRun.started_at.is_not(None),
                CustomJobRun.started_at < cutoff,
            )
        ).all()
    )
    for run in stale_runs:
        run.status = CustomJobRunStatus.FAILURE
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = "Run marked failed after exceeding stale timeout window."
    return len(stale_runs)


def claim_due_scheduled_jobs(
    *,
    db_session: Session,
    claim_limit: int = DEFAULT_CLAIM_LIMIT,
) -> list[CustomJobRun]:
    now = datetime.now(timezone.utc)
    due_jobs = list(
        db_session.scalars(
            select(CustomJob)
            .where(
                CustomJob.enabled.is_(True),
                CustomJob.trigger_type.in_(
                    [CustomJobTriggerType.DAILY, CustomJobTriggerType.WEEKLY]
                ),
                CustomJob.next_run_at.is_not(None),
                CustomJob.next_run_at <= now,
            )
            .with_for_update(skip_locked=True)
            .limit(claim_limit)
        ).all()
    )

    created_runs: list[CustomJobRun] = []
    for job in due_jobs:
        if job.next_run_at is None:
            continue

        scheduled_for = job.next_run_at
        try:
            with db_session.begin_nested():
                run = CustomJobRun(
                    custom_job_id=job.id,
                    status=CustomJobRunStatus.PENDING,
                    scheduled_for=scheduled_for,
                    trigger_event_id=None,
                )
                db_session.add(run)
                db_session.flush()
                created_runs.append(run)
        except IntegrityError:
            continue

        job.last_scheduled_at = scheduled_for
        job.next_run_at = compute_next_run_at(
            trigger_type=job.trigger_type,
            timezone_name=job.timezone,
            hour=job.hour,
            minute=job.minute,
            day_of_week=job.day_of_week,
            now_utc=scheduled_for + timedelta(seconds=1),
        )

    return created_runs


def claim_trigger_events_for_runs(
    *,
    db_session: Session,
    claim_limit: int = DEFAULT_CLAIM_LIMIT,
) -> list[CustomJobRun]:
    claim_stmt = (
        select(CustomJobTriggerEvent)
        .join(CustomJob, CustomJob.id == CustomJobTriggerEvent.custom_job_id)
        .where(
            CustomJob.enabled.is_(True),
            CustomJobTriggerEvent.status == CustomJobTriggerEventStatus.RECEIVED,
        )
        .order_by(CustomJobTriggerEvent.event_time.asc().nullsfirst())
        .with_for_update(skip_locked=True)
        .limit(claim_limit)
    )
    events = list(db_session.scalars(claim_stmt).all())
    if not events:
        return []

    job_ids = list({event.custom_job_id for event in events})
    jobs = list(
        db_session.scalars(select(CustomJob).where(CustomJob.id.in_(job_ids))).all()
    )
    jobs_by_id = {job.id: job for job in jobs}

    active_counts = dict(
        db_session.execute(
            select(CustomJobRun.custom_job_id, func.count(CustomJobRun.id))
            .where(
                CustomJobRun.custom_job_id.in_(job_ids),
                CustomJobRun.status.in_(
                    [CustomJobRunStatus.PENDING, CustomJobRunStatus.STARTED]
                ),
            )
            .group_by(CustomJobRun.custom_job_id)
        ).all()
    )
    claimed_for_job: dict[UUID, int] = {}

    runs: list[CustomJobRun] = []
    for event in events:
        job = jobs_by_id.get(event.custom_job_id)
        trigger_config = (job.trigger_source_config or {}) if job is not None else {}

        max_concurrent_runs = trigger_config.get("max_concurrent_runs")
        if isinstance(max_concurrent_runs, int) and max_concurrent_runs > 0:
            current_active = int(active_counts.get(event.custom_job_id, 0))
            current_claimed = claimed_for_job.get(event.custom_job_id, 0)
            if current_active + current_claimed >= max_concurrent_runs:
                continue

        max_events_per_claim = trigger_config.get("max_events_per_claim")
        if isinstance(max_events_per_claim, int) and max_events_per_claim > 0:
            if claimed_for_job.get(event.custom_job_id, 0) >= max_events_per_claim:
                continue

        event.status = CustomJobTriggerEventStatus.ENQUEUED
        try:
            with db_session.begin_nested():
                run = CustomJobRun(
                    custom_job_id=event.custom_job_id,
                    status=CustomJobRunStatus.PENDING,
                    scheduled_for=None,
                    trigger_event_id=event.id,
                )
                db_session.add(run)
                db_session.flush()
                runs.append(run)
                claimed_for_job[event.custom_job_id] = (
                    claimed_for_job.get(event.custom_job_id, 0) + 1
                )
        except IntegrityError:
            event.status = CustomJobTriggerEventStatus.DROPPED
            event.error_message = "Duplicate trigger event run suppressed."
            continue
    return runs


def fetch_pending_triggered_jobs(
    *,
    db_session: Session,
) -> list[CustomJob]:
    return list(
        db_session.scalars(
            select(CustomJob).where(
                CustomJob.enabled.is_(True),
                CustomJob.trigger_type == CustomJobTriggerType.TRIGGERED,
            )
        ).all()
    )


def fetch_or_create_trigger_state(
    *,
    db_session: Session,
    custom_job_id: UUID,
    source_key: str,
) -> CustomJobTriggerState:
    state = db_session.scalar(
        select(CustomJobTriggerState).where(
            CustomJobTriggerState.custom_job_id == custom_job_id,
            CustomJobTriggerState.source_key == source_key,
        )
    )
    if state is not None:
        return state
    state = CustomJobTriggerState(
        custom_job_id=custom_job_id,
        source_key=source_key,
        cursor_json=None,
    )
    db_session.add(state)
    db_session.flush()
    return state


def create_trigger_event(
    *,
    db_session: Session,
    custom_job_id: UUID,
    source_type: str,
    source_event_id: str | None,
    dedupe_key: str,
    dedupe_key_prefix: str | None,
    event_time: datetime | None,
    payload_json: dict[str, Any] | None,
) -> CustomJobTriggerEvent | None:
    event = CustomJobTriggerEvent(
        custom_job_id=custom_job_id,
        source_type=source_type,
        source_event_id=source_event_id,
        dedupe_key=dedupe_key,
        dedupe_key_prefix=dedupe_key_prefix,
        event_time=event_time,
        payload_json=payload_json,
        status=CustomJobTriggerEventStatus.RECEIVED,
    )
    try:
        with db_session.begin_nested():
            db_session.add(event)
            db_session.flush()
        return event
    except IntegrityError:
        return None


def cleanup_custom_job_history(
    *,
    db_session: Session,
) -> int:
    now = datetime.now(timezone.utc)
    jobs = list(db_session.scalars(select(CustomJob)).all())
    deleted_rows = 0

    for job in jobs:
        retention_days = job.retention_days or 90
        cutoff = now - timedelta(days=retention_days)

        terminal_runs = list(
            db_session.scalars(
                select(CustomJobRun).where(
                    CustomJobRun.custom_job_id == job.id,
                    CustomJobRun.status.in_(
                        [
                            CustomJobRunStatus.SUCCESS,
                            CustomJobRunStatus.FAILURE,
                            CustomJobRunStatus.SKIPPED,
                            CustomJobRunStatus.TIMEOUT,
                        ]
                    ),
                    CustomJobRun.created_at < cutoff,
                )
            ).all()
        )
        for run in terminal_runs:
            db_session.delete(run)
            deleted_rows += 1

        terminal_events = list(
            db_session.scalars(
                select(CustomJobTriggerEvent).where(
                    CustomJobTriggerEvent.custom_job_id == job.id,
                    CustomJobTriggerEvent.status.in_(
                        [
                            CustomJobTriggerEventStatus.CONSUMED,
                            CustomJobTriggerEventStatus.DROPPED,
                            CustomJobTriggerEventStatus.FAILED,
                        ]
                    ),
                    CustomJobTriggerEvent.created_at < cutoff,
                )
            ).all()
        )
        for event in terminal_events:
            db_session.delete(event)
            deleted_rows += 1

    return deleted_rows


def fetch_run_with_job(
    *,
    db_session: Session,
    run_id: UUID,
) -> tuple[CustomJobRun, CustomJob] | None:
    run = db_session.scalar(
        select(CustomJobRun)
        .where(CustomJobRun.id == run_id)
        .options(selectinload(CustomJobRun.custom_job))
    )
    if run is None:
        return None
    job = run.custom_job
    return run, job


def transition_run_to_started(
    *,
    db_session: Session,
    run_id: UUID,
) -> tuple[CustomJobRun, CustomJob] | None:
    now = datetime.now(timezone.utc)
    transitioned_run_id = db_session.scalar(
        update(CustomJobRun)
        .where(
            CustomJobRun.id == run_id,
            CustomJobRun.status == CustomJobRunStatus.PENDING,
        )
        .values(status=CustomJobRunStatus.STARTED, started_at=now)
        .returning(CustomJobRun.id)
    )
    if transitioned_run_id is None:
        return None

    run_and_job = fetch_run_with_job(db_session=db_session, run_id=run_id)
    if run_and_job is None:
        return None
    return run_and_job


def mark_run_terminal(
    *,
    db_session: Session,
    run: CustomJobRun,
    status: CustomJobRunStatus,
    error_message: str | None = None,
    output_preview: str | None = None,
    metrics_json: dict[str, Any] | None = None,
) -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.error_message = error_message
    run.output_preview = output_preview
    run.metrics_json = metrics_json
    if run.trigger_event_id and status in {
        CustomJobRunStatus.SUCCESS,
        CustomJobRunStatus.SKIPPED,
    }:
        event = db_session.scalar(
            select(CustomJobTriggerEvent).where(
                CustomJobTriggerEvent.id == run.trigger_event_id
            )
        )
        if event is not None:
            event.status = CustomJobTriggerEventStatus.CONSUMED
    elif run.trigger_event_id and status in {
        CustomJobRunStatus.FAILURE,
        CustomJobRunStatus.TIMEOUT,
    }:
        event = db_session.scalar(
            select(CustomJobTriggerEvent).where(
                CustomJobTriggerEvent.id == run.trigger_event_id
            )
        )
        if event is not None:
            event.status = CustomJobTriggerEventStatus.FAILED
            event.error_message = error_message


def upsert_run_step(
    *,
    db_session: Session,
    run_id: UUID,
    step_index: int,
    step_id: str,
    step_key: str,
    status: CustomJobStepStatus,
    error_message: str | None = None,
    output_json: dict[str, Any] | None = None,
    mark_started: bool = False,
) -> CustomJobRunStep:
    step = db_session.scalar(
        select(CustomJobRunStep).where(
            CustomJobRunStep.run_id == run_id,
            CustomJobRunStep.step_id == step_id,
        )
    )
    if step is None:
        step = CustomJobRunStep(
            run_id=run_id,
            step_index=step_index,
            step_id=step_id,
            step_key=step_key,
            status=status,
        )
        db_session.add(step)
    else:
        step.status = status

    now = datetime.now(timezone.utc)
    if mark_started and step.started_at is None:
        step.started_at = now
    if status in {
        CustomJobStepStatus.SUCCESS,
        CustomJobStepStatus.FAILURE,
        CustomJobStepStatus.SKIPPED,
        CustomJobStepStatus.TIMEOUT,
    }:
        step.finished_at = now
    step.error_message = error_message
    step.output_json = output_json
    db_session.flush()
    return step


def get_completed_step_outputs(
    *,
    db_session: Session,
    run_id: UUID,
) -> dict[str, dict[str, Any]]:
    completed_steps = list(
        db_session.scalars(
            select(CustomJobRunStep)
            .where(
                CustomJobRunStep.run_id == run_id,
                CustomJobRunStep.status == CustomJobStepStatus.SUCCESS,
                CustomJobRunStep.output_json.is_not(None),
            )
            .order_by(CustomJobRunStep.step_index.asc())
        ).all()
    )
    output: dict[str, dict[str, Any]] = {}
    for step in completed_steps:
        if step.output_json is None:
            continue
        output[step.step_id] = step.output_json
    return output


def try_create_run_for_trigger_event(
    *,
    db_session: Session,
    custom_job_id: UUID,
    trigger_event_id: UUID,
) -> CustomJobRun | None:
    run = CustomJobRun(
        custom_job_id=custom_job_id,
        status=CustomJobRunStatus.PENDING,
        trigger_event_id=trigger_event_id,
        scheduled_for=None,
    )
    try:
        with db_session.begin_nested():
            db_session.add(run)
            db_session.flush()
        return run
    except IntegrityError:
        return None
