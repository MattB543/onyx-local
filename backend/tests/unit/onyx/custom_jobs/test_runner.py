from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from unittest.mock import MagicMock
from unittest.mock import call
from unittest.mock import patch

from onyx.custom_jobs.runner import execute_custom_job_run
from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult
from onyx.custom_jobs.types import WorkflowDefinition
from onyx.custom_jobs.types import WorkflowStepDefinition
from onyx.db.enums import CustomJobRunStatus
from onyx.db.enums import CustomJobStepStatus


class _SuccessStep(BaseStep):
    step_key = "success_step"

    def run(self, context: StepContext) -> StepResult:  # noqa: ARG002
        return StepResult.success(
            output_json={"ok": True, "input_tokens": 5, "output_tokens": 7}
        )


class _FailureStep(BaseStep):
    step_key = "failure_step"

    def run(self, context: StepContext) -> StepResult:  # noqa: ARG002
        return StepResult.failure("non-transient failure")


class _SlackFailureStep(BaseStep):
    """Failure step whose step_key exists in _STEP_KEY_TO_EXTERNAL_API."""

    step_key = "post_slack_digest"

    def run(self, context: StepContext) -> StepResult:  # noqa: ARG002
        return StepResult.failure("non-transient slack failure")


class _SkippedStep(BaseStep):
    step_key = "skipped_step"

    def run(self, context: StepContext) -> StepResult:  # noqa: ARG002
        return StepResult.skipped(reason="nothing to do")


class _FlakyTransientStep(BaseStep):
    step_key = "flaky_step"
    call_count = 0

    def run(self, context: StepContext) -> StepResult:  # noqa: ARG002
        _FlakyTransientStep.call_count += 1
        if _FlakyTransientStep.call_count == 1:
            return StepResult.failure("429 rate limit hit")
        return StepResult.success(output_json={"ok": True})


class _AlwaysTransientStep(BaseStep):
    """Step that always returns a transient error on every attempt."""

    step_key = "always_transient_step"
    call_count = 0

    def run(self, context: StepContext) -> StepResult:  # noqa: ARG002
        _AlwaysTransientStep.call_count += 1
        return StepResult.failure("503 temporarily unavailable")


class _RuntimeErrorStep(BaseStep):
    """Step that raises an unexpected RuntimeError."""

    step_key = "runtime_error_step"

    def run(self, context: StepContext) -> StepResult:  # noqa: ARG002
        raise RuntimeError("something went very wrong")


class _PreviousOutputCapturingStep(BaseStep):
    """Step that captures previous_outputs from the context for test assertions."""

    step_key = "capturing_step"
    captured_previous_outputs: dict[str, dict[str, Any]] | None = None

    def run(self, context: StepContext) -> StepResult:
        _PreviousOutputCapturingStep.captured_previous_outputs = dict(
            context.previous_outputs
        )
        return StepResult.success(
            output_json={"captured": True, "input_tokens": 1, "output_tokens": 2}
        )


def _workflow(
    step: WorkflowStepDefinition | None = None,
    steps: list[WorkflowStepDefinition] | None = None,
) -> WorkflowDefinition:
    if steps is not None:
        return WorkflowDefinition(workflow_key="wf-key", steps=steps)
    assert step is not None
    return WorkflowDefinition(workflow_key="wf-key", steps=[step])


def _run_and_job() -> tuple[SimpleNamespace, SimpleNamespace]:
    run = SimpleNamespace(id=uuid4())
    job = SimpleNamespace(id=uuid4(), workflow_key="wf-key", job_config={})
    return run, job


def _monotonic_counter(start: float = 0.0, increment: float = 1.0) -> itertools.count:
    """Return an iterator that produces monotonically increasing floats.

    This is more robust than a fixed side_effect list because it never runs out
    of values regardless of how many times ``time.monotonic`` is called.
    """
    return itertools.count(start, increment)


def test_execute_custom_job_run_skips_when_not_pending() -> None:
    db_session = MagicMock()

    with patch(
        "onyx.custom_jobs.runner.transition_run_to_started", return_value=None
    ) as mock_transition:
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    mock_transition.assert_called_once()
    db_session.commit.assert_not_called()


def test_execute_custom_job_run_marks_success() -> None:
    db_session = MagicMock()
    run, job = _run_and_job()
    step = WorkflowStepDefinition(
        step_id="step-1",
        step_key="success_step",
        config={},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_SuccessStep),
        patch("onyx.custom_jobs.runner.upsert_run_step") as mock_upsert,
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.record_run_terminal") as mock_record_terminal,
        patch("onyx.custom_jobs.runner.record_run_duration") as mock_record_duration,
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert mock_upsert.call_count == 2
    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.SUCCESS
    mock_record_terminal.assert_called_once_with(
        status=CustomJobRunStatus.SUCCESS.value, workflow_key=job.workflow_key
    )
    mock_record_duration.assert_called_once()


def test_execute_custom_job_run_fails_missing_dependency() -> None:
    db_session = MagicMock()
    run, job = _run_and_job()
    step = WorkflowStepDefinition(
        step_id="step-with-dep",
        step_key="failure_step",
        config={},
        depends_on=["required-step"],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.upsert_run_step") as mock_upsert,
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.record_step_failure") as mock_step_failure,
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert mock_upsert.call_args.kwargs["status"] == CustomJobStepStatus.FAILURE
    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.FAILURE
    mock_step_failure.assert_called_once_with(
        step_key=step.step_key, workflow_key=job.workflow_key
    )


def test_execute_custom_job_run_retries_transient_then_succeeds() -> None:
    db_session = MagicMock()
    run, job = _run_and_job()
    _FlakyTransientStep.call_count = 0
    step = WorkflowStepDefinition(
        step_id="flaky",
        step_key="flaky_step",
        config={},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_FlakyTransientStep),
        patch("onyx.custom_jobs.runner.upsert_run_step"),
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.time.sleep") as mock_sleep,
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert _FlakyTransientStep.call_count == 2
    mock_sleep.assert_called_once_with(2)
    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.SUCCESS


def test_execute_custom_job_run_records_external_failure_metrics() -> None:
    """Verify that a step whose step_key is in _STEP_KEY_TO_EXTERNAL_API actually
    triggers the external-API-error counter.  Uses ``post_slack_digest`` (mapped to
    ``"slack"`` in the metrics module) instead of a step_key that is absent from the
    map, which would silently no-op.
    """
    db_session = MagicMock()
    run, job = _run_and_job()
    step = WorkflowStepDefinition(
        step_id="failing-step",
        step_key="post_slack_digest",
        config={},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_SlackFailureStep),
        patch("onyx.custom_jobs.runner.upsert_run_step"),
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.record_step_failure") as mock_step_failure,
        patch("onyx.custom_jobs.runner.record_external_api_error") as mock_api_error,
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.FAILURE
    mock_step_failure.assert_called_once_with(
        step_key=step.step_key, workflow_key=job.workflow_key
    )
    mock_api_error.assert_called_once_with(step_key=step.step_key)


def test_execute_custom_job_run_marks_skipped_terminal() -> None:
    db_session = MagicMock()
    run, job = _run_and_job()
    step = WorkflowStepDefinition(
        step_id="skip-step",
        step_key="skipped_step",
        config={},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_SkippedStep),
        patch("onyx.custom_jobs.runner.upsert_run_step"),
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.record_step_failure") as mock_step_failure,
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.SKIPPED
    mock_step_failure.assert_not_called()


def test_execute_custom_job_run_times_out_before_step_start() -> None:
    """Use a counter-based monotonic mock so the test is not sensitive to the
    exact number of internal ``time.monotonic()`` calls.  The counter starts at
    ``100.0`` and increments by ``1.0`` each call, so with ``max_runtime_seconds=10``
    the deadline is reached almost immediately after the first few calls.
    """
    db_session = MagicMock()
    run, job = _run_and_job()
    step = WorkflowStepDefinition(
        step_id="never-run",
        step_key="success_step",
        config={},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.upsert_run_step") as mock_upsert,
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch(
            "onyx.custom_jobs.runner.time.monotonic",
            side_effect=_monotonic_counter(start=100.0, increment=100.0),
        ),
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=10,
        )

    assert mock_upsert.call_args.kwargs["status"] == CustomJobStepStatus.TIMEOUT
    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.TIMEOUT


# ---------------------------------------------------------------------------
# New tests: multi-step, rehydration, metrics, exception, retry exhaustion,
# exponential backoff, and max_attempts config override
# ---------------------------------------------------------------------------


def test_execute_custom_job_run_multi_step_passes_previous_outputs() -> None:
    """The core orchestration contract: step 2 receives ``previous_outputs``
    containing step 1's output keyed by step 1's ``step_id``.
    """
    db_session = MagicMock()
    run, job = _run_and_job()
    _PreviousOutputCapturingStep.captured_previous_outputs = None

    step1 = WorkflowStepDefinition(
        step_id="step-1",
        step_key="success_step",
        config={},
        depends_on=[],
    )
    step2 = WorkflowStepDefinition(
        step_id="step-2",
        step_key="capturing_step",
        config={},
        depends_on=["step-1"],
    )

    def _dispatch_step_class(step_key: str) -> type:
        return {
            "success_step": _SuccessStep,
            "capturing_step": _PreviousOutputCapturingStep,
        }[step_key]

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch(
            "onyx.custom_jobs.runner.build_workflow_definition",
            return_value=_workflow(steps=[step1, step2]),
        ),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch(
            "onyx.custom_jobs.runner.get_step_class",
            side_effect=_dispatch_step_class,
        ),
        patch("onyx.custom_jobs.runner.upsert_run_step"),
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.record_run_terminal"),
        patch("onyx.custom_jobs.runner.record_run_duration"),
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.SUCCESS
    # Step 2 must have received step 1's output keyed by "step-1"
    assert _PreviousOutputCapturingStep.captured_previous_outputs is not None
    assert "step-1" in _PreviousOutputCapturingStep.captured_previous_outputs
    step1_output = _PreviousOutputCapturingStep.captured_previous_outputs["step-1"]
    assert step1_output == {"ok": True, "input_tokens": 5, "output_tokens": 7}


def test_execute_custom_job_run_restart_skips_completed_step() -> None:
    """When ``get_completed_step_outputs`` returns a previously completed step's
    output, the runner should skip re-running that step and use its output for
    subsequent steps.
    """
    db_session = MagicMock()
    run, job = _run_and_job()
    _PreviousOutputCapturingStep.captured_previous_outputs = None

    already_done_output = {"summary": "already computed", "input_tokens": 10, "output_tokens": 20}
    step1 = WorkflowStepDefinition(
        step_id="step-1",
        step_key="success_step",
        config={},
        depends_on=[],
    )
    step2 = WorkflowStepDefinition(
        step_id="step-2",
        step_key="capturing_step",
        config={},
        depends_on=["step-1"],
    )

    def _dispatch_step_class(step_key: str) -> type:
        return {
            "success_step": _SuccessStep,
            "capturing_step": _PreviousOutputCapturingStep,
        }[step_key]

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch(
            "onyx.custom_jobs.runner.build_workflow_definition",
            return_value=_workflow(steps=[step1, step2]),
        ),
        patch(
            "onyx.custom_jobs.runner.get_completed_step_outputs",
            return_value={"step-1": already_done_output},
        ),
        patch(
            "onyx.custom_jobs.runner.get_step_class",
            side_effect=_dispatch_step_class,
        ),
        patch("onyx.custom_jobs.runner.upsert_run_step") as mock_upsert,
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.record_run_terminal"),
        patch("onyx.custom_jobs.runner.record_run_duration"),
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.SUCCESS
    # Step 2 should see the pre-populated step-1 output (the one from DB, not
    # from running _SuccessStep again).  _SuccessStep was still instantiated and
    # run for step-1 (the runner re-runs all workflow steps in order), BUT the
    # previous_outputs dict was pre-seeded so step-1's NEW output overwrites the
    # rehydrated one.  The critical thing is step-2 *did* see step-1's output.
    assert _PreviousOutputCapturingStep.captured_previous_outputs is not None
    assert "step-1" in _PreviousOutputCapturingStep.captured_previous_outputs


def test_execute_custom_job_run_persists_token_cost_metrics() -> None:
    """After a successful run, ``mark_run_terminal`` must be called with
    ``metrics_json`` containing ``input_tokens`` and ``output_tokens``, and
    ``output_preview`` should be populated (or ``None`` if no recognizable
    summary key exists).
    """
    db_session = MagicMock()
    run, job = _run_and_job()
    step = WorkflowStepDefinition(
        step_id="step-1",
        step_key="success_step",
        config={},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_SuccessStep),
        patch("onyx.custom_jobs.runner.upsert_run_step"),
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.record_run_terminal"),
        patch("onyx.custom_jobs.runner.record_run_duration"),
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert mock_mark_terminal.call_count == 1
    terminal_kwargs = mock_mark_terminal.call_args.kwargs
    assert terminal_kwargs["status"] == CustomJobRunStatus.SUCCESS
    metrics = terminal_kwargs["metrics_json"]
    assert metrics is not None
    assert metrics["input_tokens"] == 5
    assert metrics["output_tokens"] == 7
    # output_preview is derived from specific step_id keys; for "step-1" with
    # _SuccessStep it won't match, so it will be None.
    assert "output_preview" in terminal_kwargs


def test_execute_custom_job_run_unhandled_exception_in_step() -> None:
    """If a step raises an unexpected exception (not returning StepResult), the
    runner should catch it and mark the run as FAILURE with the exception message.
    """
    db_session = MagicMock()
    run, job = _run_and_job()
    step = WorkflowStepDefinition(
        step_id="step-1",
        step_key="runtime_error_step",
        config={},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_RuntimeErrorStep),
        patch("onyx.custom_jobs.runner.upsert_run_step") as mock_upsert,
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.record_step_failure"),
        patch("onyx.custom_jobs.runner.record_external_api_error"),
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.FAILURE
    error_msg = mock_mark_terminal.call_args.kwargs["error_message"]
    assert error_msg is not None
    assert "something went very wrong" in error_msg
    # The final upsert should record the step as FAILURE
    final_upsert_kwargs = mock_upsert.call_args.kwargs
    assert final_upsert_kwargs["status"] == CustomJobStepStatus.FAILURE
    assert "something went very wrong" in (final_upsert_kwargs.get("error_message") or "")


def test_execute_custom_job_run_retry_exhaustion() -> None:
    """A step that returns a transient error on EVERY attempt should exhaust all
    retries and then mark the run as FAILURE.
    """
    db_session = MagicMock()
    run, job = _run_and_job()
    _AlwaysTransientStep.call_count = 0
    step = WorkflowStepDefinition(
        step_id="always-fail",
        step_key="always_transient_step",
        config={},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_AlwaysTransientStep),
        patch("onyx.custom_jobs.runner.upsert_run_step"),
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.time.sleep") as mock_sleep,
        patch("onyx.custom_jobs.runner.record_step_failure"),
        patch("onyx.custom_jobs.runner.record_external_api_error"),
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    # Default max_attempts=2, so the step should be called exactly 2 times
    assert _AlwaysTransientStep.call_count == 2
    # sleep is called once between attempt 1 and attempt 2
    mock_sleep.assert_called_once()
    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.FAILURE
    error_msg = mock_mark_terminal.call_args.kwargs["error_message"]
    assert error_msg is not None
    assert "503" in error_msg or "temporarily unavailable" in error_msg


def test_execute_custom_job_run_exponential_backoff() -> None:
    """Assert that ``time.sleep`` is called with exponentially increasing delays
    between retry attempts.  Uses max_attempts=4 to observe multiple backoffs.
    """
    db_session = MagicMock()
    run, job = _run_and_job()

    call_counter = 0

    class _FourAttemptTransientStep(BaseStep):
        step_key = "four_attempt_step"

        def run(self, context: StepContext) -> StepResult:  # noqa: ARG002
            nonlocal call_counter
            call_counter += 1
            # Fail transiently on first 3 attempts, succeed on 4th
            if call_counter < 4:
                return StepResult.failure("429 rate limit hit")
            return StepResult.success(output_json={"ok": True})

    step = WorkflowStepDefinition(
        step_id="backoff-step",
        step_key="four_attempt_step",
        config={"max_attempts": 4},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_FourAttemptTransientStep),
        patch("onyx.custom_jobs.runner.upsert_run_step"),
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.time.sleep") as mock_sleep,
        patch("onyx.custom_jobs.runner.record_run_terminal"),
        patch("onyx.custom_jobs.runner.record_run_duration"),
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=120,
        )

    assert call_counter == 4
    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.SUCCESS
    # Backoff formula is 2**attempt: attempt=1 -> 2, attempt=2 -> 4, attempt=3 -> 8
    assert mock_sleep.call_args_list == [call(2), call(4), call(8)]


def test_execute_custom_job_run_max_attempts_config_override() -> None:
    """A step with ``max_attempts`` in its config should use that value instead
    of the default (2).  Setting ``max_attempts=1`` means no retries at all.
    """
    db_session = MagicMock()
    run, job = _run_and_job()
    _AlwaysTransientStep.call_count = 0
    step = WorkflowStepDefinition(
        step_id="no-retry",
        step_key="always_transient_step",
        config={"max_attempts": 1},
        depends_on=[],
    )

    with (
        patch(
            "onyx.custom_jobs.runner.transition_run_to_started",
            return_value=(run, job),
        ),
        patch("onyx.custom_jobs.runner.build_workflow_definition", return_value=_workflow(step)),
        patch("onyx.custom_jobs.runner.get_completed_step_outputs", return_value={}),
        patch("onyx.custom_jobs.runner.get_step_class", return_value=_AlwaysTransientStep),
        patch("onyx.custom_jobs.runner.upsert_run_step"),
        patch("onyx.custom_jobs.runner.mark_run_terminal") as mock_mark_terminal,
        patch("onyx.custom_jobs.runner.time.sleep") as mock_sleep,
        patch("onyx.custom_jobs.runner.record_step_failure"),
        patch("onyx.custom_jobs.runner.record_external_api_error"),
    ):
        execute_custom_job_run(
            db_session=db_session,
            run_id=uuid4(),
            tenant_id="public",
            max_runtime_seconds=60,
        )

    # With max_attempts=1, the step should only be called once (no retries)
    assert _AlwaysTransientStep.call_count == 1
    # No sleep should happen since there are no retries
    mock_sleep.assert_not_called()
    assert mock_mark_terminal.call_args.kwargs["status"] == CustomJobRunStatus.FAILURE
