from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.custom_jobs.metrics import record_external_api_error
from onyx.custom_jobs.metrics import record_run_duration
from onyx.custom_jobs.metrics import record_run_terminal
from onyx.custom_jobs.metrics import record_step_failure
from onyx.custom_jobs.registry import build_workflow_definition
from onyx.custom_jobs.registry import get_step_class
from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult
from onyx.db.custom_jobs import get_completed_step_outputs
from onyx.db.custom_jobs import mark_run_terminal
from onyx.db.custom_jobs import transition_run_to_started
from onyx.db.custom_jobs import upsert_run_step
from onyx.db.enums import CustomJobRunStatus
from onyx.db.enums import CustomJobStepStatus
from onyx.utils.logger import setup_logger

logger = setup_logger()

TRANSIENT_ERROR_INDICATORS = (
    "rate limit",
    "429",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "connection reset",
    "502",
    "503",
    "504",
)


def _is_transient_error(error_message: str | None) -> bool:
    if not error_message:
        return False
    lowered = error_message.lower()
    return any(indicator in lowered for indicator in TRANSIENT_ERROR_INDICATORS)


def _build_output_preview(previous_outputs: dict[str, dict[str, Any]]) -> str | None:
    summary = (
        previous_outputs.get("summarize_weekly_content", {}).get("summary")
        or previous_outputs.get("google_doc_output", {}).get("doc_url")
        or ""
    )
    summary = str(summary).strip()
    if not summary:
        return None
    return summary[:2000]


def _collect_metrics(previous_outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total_input_tokens = 0
    total_output_tokens = 0
    for payload in previous_outputs.values():
        total_input_tokens += int(payload.get("input_tokens", 0))
        total_output_tokens += int(payload.get("output_tokens", 0))
    return {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    }


def execute_custom_job_run(
    *,
    db_session: Session,
    run_id: UUID,
    tenant_id: str,
    max_runtime_seconds: int,
) -> None:
    run_start_monotonic = time.monotonic()
    transitioned = transition_run_to_started(db_session=db_session, run_id=run_id)
    if transitioned is None:
        logger.info(
            "custom_job_run_skipped_non_pending tenant_id=%s run_id=%s",
            tenant_id,
            run_id,
        )
        return

    run, job = transitioned
    db_session.commit()
    run_start_monotonic = time.monotonic()

    logger.info(
        "custom_job_run_started tenant_id=%s job_id=%s run_id=%s workflow_key=%s max_runtime_seconds=%s",
        tenant_id,
        job.id,
        run.id,
        job.workflow_key,
        max_runtime_seconds,
    )

    workflow = build_workflow_definition(
        workflow_key=job.workflow_key,
        job_config=job.job_config or {},
    )
    previous_outputs = get_completed_step_outputs(db_session=db_session, run_id=run.id)
    deadline = time.monotonic() + max_runtime_seconds

    def _mark_run_terminal_and_commit(
        *,
        status: CustomJobRunStatus,
        error_message: str | None = None,
    ) -> None:
        mark_run_terminal(
            db_session=db_session,
            run=run,
            status=status,
            error_message=error_message,
            output_preview=_build_output_preview(previous_outputs),
            metrics_json=_collect_metrics(previous_outputs),
        )
        db_session.commit()
        elapsed_seconds = time.monotonic() - run_start_monotonic
        logger.info(
            "custom_job_run_finished tenant_id=%s job_id=%s run_id=%s "
            "workflow_key=%s status=%s latency_seconds=%.3f error_message=%s",
            tenant_id,
            job.id,
            run.id,
            job.workflow_key,
            status.value,
            elapsed_seconds,
            error_message,
        )
        record_run_terminal(status=status.value, workflow_key=job.workflow_key)
        record_run_duration(
            duration_seconds=elapsed_seconds,
            workflow_key=job.workflow_key,
            status=status.value,
        )

    for step_index, step_def in enumerate(workflow.steps):
        if time.monotonic() > deadline:
            upsert_run_step(
                db_session=db_session,
                run_id=run.id,
                step_index=step_index,
                step_id=step_def.step_id,
                step_key=step_def.step_key,
                status=CustomJobStepStatus.TIMEOUT,
                error_message="Run exceeded max runtime before step start.",
            )
            _mark_run_terminal_and_commit(
                status=CustomJobRunStatus.TIMEOUT,
                error_message="Run exceeded max runtime.",
            )
            return

        for dependency in step_def.depends_on:
            if dependency not in previous_outputs:
                upsert_run_step(
                    db_session=db_session,
                    run_id=run.id,
                    step_index=step_index,
                    step_id=step_def.step_id,
                    step_key=step_def.step_key,
                    status=CustomJobStepStatus.FAILURE,
                    error_message=f"Missing dependency output: {dependency}",
                )
                record_step_failure(
                    step_key=step_def.step_key, workflow_key=job.workflow_key
                )
                _mark_run_terminal_and_commit(
                    status=CustomJobRunStatus.FAILURE,
                    error_message=f"Missing dependency output: {dependency}",
                )
                return

        step_cls = get_step_class(step_def.step_key)
        step_instance: BaseStep = step_cls()

        max_attempts = max(1, int(step_def.config.get("max_attempts", 2)))
        attempt = 0
        final_result: StepResult | None = None

        while attempt < max_attempts:
            attempt += 1
            attempt_start_monotonic = time.monotonic()
            logger.info(
                "custom_job_step_started tenant_id=%s job_id=%s run_id=%s step_id=%s step_key=%s attempt=%s max_attempts=%s",
                tenant_id,
                job.id,
                run.id,
                step_def.step_id,
                step_def.step_key,
                attempt,
                max_attempts,
            )
            upsert_run_step(
                db_session=db_session,
                run_id=run.id,
                step_index=step_index,
                step_id=step_def.step_id,
                step_key=step_def.step_key,
                status=CustomJobStepStatus.STARTED,
                mark_started=True,
            )
            db_session.commit()

            try:
                step_context = StepContext(
                    db_session=db_session,
                    tenant_id=tenant_id,
                    run_id=run.id,
                    job_id=job.id,
                    job_config=job.job_config or {},
                    step_config=step_def.config,
                    previous_outputs=previous_outputs,
                    deadline_monotonic=deadline,
                )
                final_result = step_instance.run(step_context)
            except Exception as e:
                final_result = StepResult.failure(f"Step execution error: {e}")

            if (
                final_result.status == CustomJobStepStatus.FAILURE
                and _is_transient_error(final_result.error_message)
                and attempt < max_attempts
            ):
                backoff_seconds = 2**attempt
                logger.warning(
                    "custom_job_step_retry tenant_id=%s job_id=%s run_id=%s "
                    "step_id=%s step_key=%s attempt=%s max_attempts=%s "
                    "backoff_seconds=%s error_message=%s",
                    tenant_id,
                    job.id,
                    run.id,
                    step_def.step_id,
                    step_def.step_key,
                    attempt,
                    max_attempts,
                    backoff_seconds,
                    final_result.error_message,
                )
                time.sleep(backoff_seconds)
                continue
            break

        assert final_result is not None
        step_elapsed_seconds = time.monotonic() - attempt_start_monotonic

        upsert_run_step(
            db_session=db_session,
            run_id=run.id,
            step_index=step_index,
            step_id=step_def.step_id,
            step_key=step_def.step_key,
            status=final_result.status,
            error_message=final_result.error_message,
            output_json=final_result.output_json,
        )
        logger.info(
            "custom_job_step_finished tenant_id=%s job_id=%s run_id=%s "
            "step_id=%s step_key=%s status=%s attempt=%s max_attempts=%s "
            "latency_seconds=%.3f error_message=%s",
            tenant_id,
            job.id,
            run.id,
            step_def.step_id,
            step_def.step_key,
            final_result.status.value,
            attempt,
            max_attempts,
            step_elapsed_seconds,
            final_result.error_message,
        )

        if final_result.status == CustomJobStepStatus.SUCCESS:
            previous_outputs[step_def.step_id] = final_result.output_json or {}
            db_session.commit()
            continue

        if final_result.status == CustomJobStepStatus.SKIPPED:
            _mark_run_terminal_and_commit(
                status=CustomJobRunStatus.SKIPPED,
                error_message=final_result.error_message,
            )
            return

        terminal_status = (
            CustomJobRunStatus.TIMEOUT
            if final_result.status == CustomJobStepStatus.TIMEOUT
            else CustomJobRunStatus.FAILURE
        )
        record_step_failure(step_key=step_def.step_key, workflow_key=job.workflow_key)
        record_external_api_error(step_key=step_def.step_key)
        _mark_run_terminal_and_commit(
            status=terminal_status,
            error_message=final_result.error_message,
        )
        return

    _mark_run_terminal_and_commit(status=CustomJobRunStatus.SUCCESS)
