import time
from uuid import UUID

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import ENABLE_CUSTOM_JOBS
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.custom_jobs.runner import execute_custom_job_run
from onyx.db.custom_jobs import claim_due_scheduled_jobs
from onyx.db.custom_jobs import claim_trigger_events_for_runs
from onyx.db.custom_jobs import cleanup_custom_job_history
from onyx.db.custom_jobs import mark_stale_started_runs_failed
from onyx.db.custom_jobs import fetch_pending_triggered_jobs
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import redis_lock_dump


def _enqueue_run_task(task: Task, run_id: UUID, tenant_id: str) -> None:
    task.app.send_task(
        OnyxCeleryTask.RUN_CUSTOM_JOB,
        kwargs={"run_id": str(run_id), "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.CSV_GENERATION,
        priority=OnyxCeleryPriority.MEDIUM,
    )


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_CUSTOM_JOBS,
    soft_time_limit=300,
    ignore_result=True,
    trail=False,
    bind=True,
)
def check_for_custom_jobs(self: Task, *, tenant_id: str) -> int | None:
    if not ENABLE_CUSTOM_JOBS:
        return None

    locked = False
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_CUSTOM_JOBS_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    if not lock_beat.acquire(blocking=False):
        return None

    time_start = time.monotonic()
    try:
        locked = True
        with get_session_with_current_tenant() as db_session:
            stale_runs = mark_stale_started_runs_failed(
                db_session=db_session,
                max_runtime_seconds=JOB_TIMEOUT,
            )
            due_runs = claim_due_scheduled_jobs(db_session=db_session)
            db_session.commit()

            for run in due_runs:
                lock_beat.reacquire()
                _enqueue_run_task(self, run.id, tenant_id)

        task_logger.info(
            "check_for_custom_jobs finished: tenant=%s due_runs=%s stale_runs=%s elapsed=%.2fs",
            tenant_id,
            len(due_runs),
            stale_runs,
            time.monotonic() - time_start,
        )
        return len(due_runs)
    except SoftTimeLimitExceeded:
        task_logger.info("check_for_custom_jobs soft time limit reached.")
        return None
    except Exception:
        task_logger.exception("Unexpected error in check_for_custom_jobs.")
        return None
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "check_for_custom_jobs - lock not owned on completion: tenant=%s",
                    tenant_id,
                )
                redis_lock_dump(lock_beat, redis_client)


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_CUSTOM_JOB_TRIGGER_EVENTS,
    soft_time_limit=300,
    ignore_result=True,
    trail=False,
    bind=True,
)
def check_for_custom_job_trigger_events(self: Task, *, tenant_id: str) -> int | None:
    if not ENABLE_CUSTOM_JOBS:
        return None

    locked = False
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_CUSTOM_JOB_TRIGGER_EVENTS_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    if not lock_beat.acquire(blocking=False):
        return None

    try:
        locked = True
        with get_session_with_current_tenant() as db_session:
            runs = claim_trigger_events_for_runs(db_session=db_session)
            db_session.commit()

        for run in runs:
            lock_beat.reacquire()
            _enqueue_run_task(self, run.id, tenant_id)

        return len(runs)
    except SoftTimeLimitExceeded:
        task_logger.info("check_for_custom_job_trigger_events soft time limit reached.")
        return None
    except Exception:
        task_logger.exception("Unexpected error in check_for_custom_job_trigger_events.")
        return None
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "check_for_custom_job_trigger_events - lock not owned on completion: tenant=%s",
                    tenant_id,
                )
                redis_lock_dump(lock_beat, redis_client)


@shared_task(
    name=OnyxCeleryTask.POLL_CUSTOM_JOB_TRIGGERS,
    soft_time_limit=300,
    ignore_result=True,
    trail=False,
    bind=True,
)
def poll_custom_job_triggers(self: Task, *, tenant_id: str) -> int | None:  # noqa: ARG001
    """Poll trigger sources and persist trigger events.

    v1 baseline keeps this lightweight and no-op unless a trigger adapter is added.
    """
    if not ENABLE_CUSTOM_JOBS:
        return None

    locked = False
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.POLL_CUSTOM_JOB_TRIGGERS_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    if not lock_beat.acquire(blocking=False):
        return None

    try:
        locked = True
        with get_session_with_current_tenant() as db_session:
            pending_trigger_jobs = fetch_pending_triggered_jobs(db_session=db_session)
        task_logger.debug(
            "poll_custom_job_triggers no-op pass: tenant=%s jobs=%s",
            tenant_id,
            len(pending_trigger_jobs),
        )
        return len(pending_trigger_jobs)
    except SoftTimeLimitExceeded:
        task_logger.info("poll_custom_job_triggers soft time limit reached.")
        return None
    except Exception:
        task_logger.exception("Unexpected error in poll_custom_job_triggers.")
        return None
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "poll_custom_job_triggers - lock not owned on completion: tenant=%s",
                    tenant_id,
                )
                redis_lock_dump(lock_beat, redis_client)


@shared_task(
    name=OnyxCeleryTask.CLEANUP_CUSTOM_JOB_HISTORY,
    soft_time_limit=300,
    ignore_result=True,
    trail=False,
    bind=True,
)
def cleanup_custom_job_history_task(self: Task, *, tenant_id: str) -> int | None:  # noqa: ARG001
    if not ENABLE_CUSTOM_JOBS:
        return None

    locked = False
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CLEANUP_CUSTOM_JOB_HISTORY_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    if not lock_beat.acquire(blocking=False):
        return None

    try:
        locked = True
        with get_session_with_current_tenant() as db_session:
            deleted_rows = cleanup_custom_job_history(db_session=db_session)
            db_session.commit()
        return deleted_rows
    except SoftTimeLimitExceeded:
        task_logger.info("cleanup_custom_job_history_task soft time limit reached.")
        return None
    except Exception:
        task_logger.exception("Unexpected error in cleanup_custom_job_history_task.")
        return None
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "cleanup_custom_job_history_task - lock not owned on completion: tenant=%s",
                    tenant_id,
                )
                redis_lock_dump(lock_beat, redis_client)


@shared_task(
    name=OnyxCeleryTask.RUN_CUSTOM_JOB,
    acks_late=False,
    track_started=True,
    bind=True,
)
def run_custom_job(
    self: Task, *, run_id: str, tenant_id: str  # noqa: ARG001
) -> None:
    if not ENABLE_CUSTOM_JOBS:
        return None
    with get_session_with_current_tenant() as db_session:
        execute_custom_job_run(
            db_session=db_session,
            run_id=UUID(run_id),
            tenant_id=tenant_id,
            max_runtime_seconds=JOB_TIMEOUT,
        )

