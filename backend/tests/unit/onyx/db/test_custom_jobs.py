from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from unittest.mock import MagicMock
from unittest.mock import call
from unittest.mock import patch

from onyx.db.custom_jobs import claim_due_scheduled_jobs
from onyx.db.custom_jobs import claim_trigger_events_for_runs
from onyx.db.custom_jobs import cleanup_custom_job_history
from onyx.db.custom_jobs import compute_next_run_at
from onyx.db.custom_jobs import create_manual_run_if_allowed
from onyx.db.custom_jobs import create_trigger_event
from onyx.db.custom_jobs import fetch_or_create_trigger_state
from onyx.db.custom_jobs import mark_run_terminal
from onyx.db.custom_jobs import mark_stale_started_runs_failed
from onyx.db.custom_jobs import transition_run_to_started
from onyx.db.custom_jobs import upsert_run_step
from onyx.db.enums import CustomJobRunStatus
from onyx.db.enums import CustomJobStepStatus
from onyx.db.enums import CustomJobTriggerEventStatus
from onyx.db.enums import CustomJobTriggerType


class _NoopContextManager:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False


def _mock_scalar_all(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = items
    return result


class TestComputeNextRunAt:
    def test_triggered_jobs_return_none(self) -> None:
        assert (
            compute_next_run_at(
                trigger_type=CustomJobTriggerType.TRIGGERED,
                timezone_name=None,
                hour=None,
                minute=None,
                day_of_week=None,
            )
            is None
        )

    def test_daily_schedule_uses_local_time(self) -> None:
        now_utc = datetime(2026, 2, 18, 12, 30, tzinfo=timezone.utc)
        next_run = compute_next_run_at(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="UTC",
            hour=13,
            minute=0,
            day_of_week=None,
            now_utc=now_utc,
        )

        assert next_run == datetime(2026, 2, 18, 13, 0, tzinfo=timezone.utc)

    def test_weekly_schedule_targets_next_weekday(self) -> None:
        # Feb 18, 2026 is Wednesday; next Monday is Feb 23, 2026.
        now_utc = datetime(2026, 2, 18, 12, 30, tzinfo=timezone.utc)
        next_run = compute_next_run_at(
            trigger_type=CustomJobTriggerType.WEEKLY,
            timezone_name="UTC",
            hour=1,
            minute=0,
            day_of_week=0,
            now_utc=now_utc,
        )

        assert next_run == datetime(2026, 2, 23, 1, 0, tzinfo=timezone.utc)

    def test_invalid_hour_raises(self) -> None:
        with pytest.raises(ValueError, match="hour must be between 0 and 23"):
            compute_next_run_at(
                trigger_type=CustomJobTriggerType.DAILY,
                timezone_name="UTC",
                hour=24,
                minute=0,
                day_of_week=None,
            )


class TestCreateManualRunIfAllowed:
    def test_returns_existing_run_for_idempotency_key(self) -> None:
        job = SimpleNamespace(id=uuid4())
        existing_run = SimpleNamespace(
            id=uuid4(), created_at=datetime.now(timezone.utc)
        )
        db_session = MagicMock()
        db_session.scalar.return_value = existing_run

        result = create_manual_run_if_allowed(
            db_session=db_session, job=job, idempotency_key="idem-1"
        )

        assert result.run == existing_run
        assert result.created is False
        db_session.add.assert_not_called()

    def test_enforces_cooldown(self) -> None:
        job = SimpleNamespace(id=uuid4())
        recent_run = SimpleNamespace(created_at=datetime.now(timezone.utc))
        db_session = MagicMock()
        db_session.scalar.side_effect = [None, recent_run]

        with pytest.raises(ValueError, match="Manual trigger cooldown active"):
            create_manual_run_if_allowed(
                db_session=db_session,
                job=job,
                cooldown_seconds=60,
                idempotency_key="idem-2",
            )

    def test_creates_run_when_allowed(self) -> None:
        job = SimpleNamespace(id=uuid4())
        db_session = MagicMock()
        db_session.scalar.side_effect = [None, None]
        db_session.begin_nested.return_value = _NoopContextManager()

        result = create_manual_run_if_allowed(
            db_session=db_session,
            job=job,
            idempotency_key="idem-3",
        )

        assert result.created is True
        assert result.run.custom_job_id == job.id
        assert result.run.idempotency_key == "idem-3"
        db_session.add.assert_called_once()
        db_session.flush.assert_called_once()

    def test_handles_race_and_returns_deduped_run(self) -> None:
        job = SimpleNamespace(id=uuid4())
        deduped_run = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(timezone.utc),
            idempotency_key="idem-race",
        )
        db_session = MagicMock()
        db_session.scalar.side_effect = [None, None, deduped_run]
        db_session.begin_nested.return_value = _NoopContextManager()
        db_session.flush.side_effect = IntegrityError("stmt", "params", Exception())

        result = create_manual_run_if_allowed(
            db_session=db_session,
            job=job,
            idempotency_key="idem-race",
        )

        assert result.created is False
        assert result.run == deduped_run


class TestClaimTriggerEventsForRuns:
    def test_respects_concurrency_and_claim_limits(self) -> None:
        job_id = uuid4()
        event_one = SimpleNamespace(
            id=uuid4(),
            custom_job_id=job_id,
            status=CustomJobTriggerEventStatus.RECEIVED,
            error_message=None,
        )
        event_two = SimpleNamespace(
            id=uuid4(),
            custom_job_id=job_id,
            status=CustomJobTriggerEventStatus.RECEIVED,
            error_message=None,
        )
        job = SimpleNamespace(
            id=job_id,
            trigger_source_config={"max_concurrent_runs": 1, "max_events_per_claim": 1},
        )

        db_session = MagicMock()
        db_session.scalars.side_effect = [
            _mock_scalar_all([event_one, event_two]),
            _mock_scalar_all([job]),
        ]
        db_session.execute.return_value.all.return_value = [(job_id, 0)]
        db_session.begin_nested.return_value = _NoopContextManager()

        runs = claim_trigger_events_for_runs(db_session=db_session, claim_limit=50)

        assert len(runs) == 1
        assert event_one.status == CustomJobTriggerEventStatus.ENQUEUED
        assert event_two.status == CustomJobTriggerEventStatus.RECEIVED

    def test_marks_event_dropped_when_run_insert_conflicts(self) -> None:
        job_id = uuid4()
        event = SimpleNamespace(
            id=uuid4(),
            custom_job_id=job_id,
            status=CustomJobTriggerEventStatus.RECEIVED,
            error_message=None,
        )
        job = SimpleNamespace(id=job_id, trigger_source_config={})

        db_session = MagicMock()
        db_session.scalars.side_effect = [
            _mock_scalar_all([event]),
            _mock_scalar_all([job]),
        ]
        db_session.execute.return_value.all.return_value = []
        db_session.begin_nested.return_value = _NoopContextManager()
        db_session.flush.side_effect = IntegrityError("stmt", "params", Exception())

        runs = claim_trigger_events_for_runs(db_session=db_session, claim_limit=50)

        assert runs == []
        assert event.status == CustomJobTriggerEventStatus.DROPPED
        assert "Duplicate trigger event run suppressed" in str(event.error_message)


class TestTransitionRunToStarted:
    def test_returns_none_if_run_not_transitioned(self) -> None:
        db_session = MagicMock()
        db_session.scalar.return_value = None

        result = transition_run_to_started(db_session=db_session, run_id=uuid4())

        assert result is None

    def test_returns_run_and_job_when_transition_succeeds(self) -> None:
        run_id = uuid4()
        db_session = MagicMock()
        db_session.scalar.return_value = run_id
        run = SimpleNamespace(id=run_id, status=CustomJobRunStatus.STARTED)
        job = SimpleNamespace(id=uuid4())

        with patch(
            "onyx.db.custom_jobs.fetch_run_with_job", return_value=(run, job)
        ) as mock_fetch:
            result = transition_run_to_started(db_session=db_session, run_id=run_id)

        assert result == (run, job)
        mock_fetch.assert_called_once_with(db_session=db_session, run_id=run_id)


class TestClaimTriggerEventsMaxEventsPerClaimOnly:
    """Exercise max_events_per_claim independently from max_concurrent_runs (item 9)."""

    def test_max_events_per_claim_limits_independently(self) -> None:
        job_id = uuid4()
        events = [
            SimpleNamespace(
                id=uuid4(),
                custom_job_id=job_id,
                status=CustomJobTriggerEventStatus.RECEIVED,
                error_message=None,
            )
            for _ in range(3)
        ]
        job = SimpleNamespace(
            id=job_id,
            trigger_source_config={"max_events_per_claim": 2},
        )

        db_session = MagicMock()
        db_session.scalars.side_effect = [
            _mock_scalar_all(events),
            _mock_scalar_all([job]),
        ]
        # No active runs at all -- concurrency is not the limiter here.
        db_session.execute.return_value.all.return_value = []
        db_session.begin_nested.return_value = _NoopContextManager()

        runs = claim_trigger_events_for_runs(db_session=db_session, claim_limit=50)

        assert len(runs) == 2
        assert events[0].status == CustomJobTriggerEventStatus.ENQUEUED
        assert events[1].status == CustomJobTriggerEventStatus.ENQUEUED
        # Third event untouched because max_events_per_claim=2.
        assert events[2].status == CustomJobTriggerEventStatus.RECEIVED


class TestClaimDueScheduledJobs:
    def test_creates_runs_for_due_jobs_and_advances_next_run(self) -> None:
        now_utc = datetime(2026, 2, 18, 14, 0, tzinfo=timezone.utc)
        job = SimpleNamespace(
            id=uuid4(),
            next_run_at=datetime(2026, 2, 18, 13, 0, tzinfo=timezone.utc),
            trigger_type=CustomJobTriggerType.DAILY,
            timezone="UTC",
            hour=13,
            minute=0,
            day_of_week=None,
            enabled=True,
            last_scheduled_at=None,
        )

        db_session = MagicMock()
        db_session.scalars.return_value.all.return_value = [job]
        db_session.begin_nested.return_value = _NoopContextManager()

        with patch("onyx.db.custom_jobs.datetime") as mock_dt:
            mock_dt.now.return_value = now_utc
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            runs = claim_due_scheduled_jobs(db_session=db_session)

        assert len(runs) == 1
        assert runs[0].custom_job_id == job.id
        assert runs[0].status == CustomJobRunStatus.PENDING
        assert runs[0].scheduled_for == datetime(
            2026, 2, 18, 13, 0, tzinfo=timezone.utc
        )
        assert job.last_scheduled_at == datetime(
            2026, 2, 18, 13, 0, tzinfo=timezone.utc
        )
        # next_run_at should be advanced (tomorrow at 13:00 UTC).
        assert job.next_run_at == datetime(2026, 2, 19, 13, 0, tzinfo=timezone.utc)

    def test_skips_job_when_run_insert_conflicts(self) -> None:
        job = SimpleNamespace(
            id=uuid4(),
            next_run_at=datetime(2026, 2, 18, 13, 0, tzinfo=timezone.utc),
            trigger_type=CustomJobTriggerType.DAILY,
            timezone="UTC",
            hour=13,
            minute=0,
            day_of_week=None,
            enabled=True,
            last_scheduled_at=None,
        )

        db_session = MagicMock()
        db_session.scalars.return_value.all.return_value = [job]
        db_session.begin_nested.return_value = _NoopContextManager()
        db_session.flush.side_effect = IntegrityError("stmt", "params", Exception())

        now_utc = datetime(2026, 2, 18, 14, 0, tzinfo=timezone.utc)
        with patch("onyx.db.custom_jobs.datetime") as mock_dt:
            mock_dt.now.return_value = now_utc
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            runs = claim_due_scheduled_jobs(db_session=db_session)

        assert runs == []

    def test_returns_empty_when_no_due_jobs(self) -> None:
        db_session = MagicMock()
        db_session.scalars.return_value.all.return_value = []

        runs = claim_due_scheduled_jobs(db_session=db_session)
        assert runs == []


class TestMarkStaleStartedRunsFailed:
    def test_marks_stale_runs_failed(self) -> None:
        max_runtime = 3600  # 1 hour
        # Stale run: started 3 hours ago (> 2 * max_runtime = 2 hours).
        stale_run = SimpleNamespace(
            id=uuid4(),
            status=CustomJobRunStatus.STARTED,
            started_at=datetime.now(timezone.utc) - timedelta(hours=3),
            finished_at=None,
            error_message=None,
        )
        db_session = MagicMock()
        db_session.scalars.return_value.all.return_value = [stale_run]

        count = mark_stale_started_runs_failed(
            db_session=db_session,
            max_runtime_seconds=max_runtime,
        )

        assert count == 1
        assert stale_run.status == CustomJobRunStatus.FAILURE
        assert stale_run.finished_at is not None
        assert "stale timeout" in stale_run.error_message

    def test_leaves_fresh_runs_untouched(self) -> None:
        max_runtime = 3600
        db_session = MagicMock()
        # No stale runs returned by the DB query.
        db_session.scalars.return_value.all.return_value = []

        count = mark_stale_started_runs_failed(
            db_session=db_session,
            max_runtime_seconds=max_runtime,
        )

        assert count == 0


class TestCleanupCustomJobHistory:
    def test_deletes_terminal_runs_and_events_older_than_retention(self) -> None:
        job = SimpleNamespace(id=uuid4(), retention_days=30)
        old_run = SimpleNamespace(
            id=uuid4(),
            custom_job_id=job.id,
            status=CustomJobRunStatus.SUCCESS,
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        old_event = SimpleNamespace(
            id=uuid4(),
            custom_job_id=job.id,
            status=CustomJobTriggerEventStatus.CONSUMED,
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        )

        db_session = MagicMock()
        # First scalars call: list of jobs. Then two more for runs/events per job.
        db_session.scalars.return_value.all.side_effect = [
            [job],
            [old_run],
            [old_event],
        ]

        deleted = cleanup_custom_job_history(db_session=db_session)

        assert deleted == 2
        assert db_session.delete.call_count == 2
        db_session.delete.assert_any_call(old_run)
        db_session.delete.assert_any_call(old_event)

    def test_preserves_recent_runs_and_events(self) -> None:
        job = SimpleNamespace(id=uuid4(), retention_days=90)

        db_session = MagicMock()
        # Jobs come back, but no terminal runs or events within cutoff.
        db_session.scalars.return_value.all.side_effect = [
            [job],
            [],
            [],
        ]

        deleted = cleanup_custom_job_history(db_session=db_session)

        assert deleted == 0
        db_session.delete.assert_not_called()

    def test_uses_default_retention_when_none(self) -> None:
        job = SimpleNamespace(id=uuid4(), retention_days=None)

        db_session = MagicMock()
        db_session.scalars.return_value.all.side_effect = [
            [job],
            [],
            [],
        ]

        # Should not raise -- defaults to 90 days.
        deleted = cleanup_custom_job_history(db_session=db_session)
        assert deleted == 0


class TestMarkRunTerminal:
    def test_sets_all_terminal_fields(self) -> None:
        run = SimpleNamespace(
            id=uuid4(),
            status=CustomJobRunStatus.STARTED,
            finished_at=None,
            error_message=None,
            output_preview=None,
            metrics_json=None,
            trigger_event_id=None,
        )
        db_session = MagicMock()

        mark_run_terminal(
            db_session=db_session,
            run=run,
            status=CustomJobRunStatus.FAILURE,
            error_message="something went wrong",
            output_preview="preview text",
            metrics_json={"rows": 42},
        )

        assert run.status == CustomJobRunStatus.FAILURE
        assert run.finished_at is not None
        assert run.error_message == "something went wrong"
        assert run.output_preview == "preview text"
        assert run.metrics_json == {"rows": 42}

    def test_marks_trigger_event_consumed_on_success(self) -> None:
        trigger_event_id = uuid4()
        run = SimpleNamespace(
            id=uuid4(),
            status=CustomJobRunStatus.STARTED,
            finished_at=None,
            error_message=None,
            output_preview=None,
            metrics_json=None,
            trigger_event_id=trigger_event_id,
        )
        event = SimpleNamespace(
            id=trigger_event_id,
            status=CustomJobTriggerEventStatus.ENQUEUED,
            error_message=None,
        )
        db_session = MagicMock()
        db_session.scalar.return_value = event

        mark_run_terminal(
            db_session=db_session,
            run=run,
            status=CustomJobRunStatus.SUCCESS,
        )

        assert run.status == CustomJobRunStatus.SUCCESS
        assert event.status == CustomJobTriggerEventStatus.CONSUMED

    def test_marks_trigger_event_failed_on_failure(self) -> None:
        trigger_event_id = uuid4()
        run = SimpleNamespace(
            id=uuid4(),
            status=CustomJobRunStatus.STARTED,
            finished_at=None,
            error_message=None,
            output_preview=None,
            metrics_json=None,
            trigger_event_id=trigger_event_id,
        )
        event = SimpleNamespace(
            id=trigger_event_id,
            status=CustomJobTriggerEventStatus.ENQUEUED,
            error_message=None,
        )
        db_session = MagicMock()
        db_session.scalar.return_value = event

        mark_run_terminal(
            db_session=db_session,
            run=run,
            status=CustomJobRunStatus.FAILURE,
            error_message="task crashed",
        )

        assert event.status == CustomJobTriggerEventStatus.FAILED
        assert event.error_message == "task crashed"

    def test_no_event_lookup_when_no_trigger_event(self) -> None:
        run = SimpleNamespace(
            id=uuid4(),
            status=CustomJobRunStatus.STARTED,
            finished_at=None,
            error_message=None,
            output_preview=None,
            metrics_json=None,
            trigger_event_id=None,
        )
        db_session = MagicMock()

        mark_run_terminal(
            db_session=db_session,
            run=run,
            status=CustomJobRunStatus.SUCCESS,
        )

        db_session.scalar.assert_not_called()


class TestUpsertRunStep:
    def test_creates_new_step(self) -> None:
        run_id = uuid4()
        db_session = MagicMock()
        db_session.scalar.return_value = None  # No existing step.

        step = upsert_run_step(
            db_session=db_session,
            run_id=run_id,
            step_index=0,
            step_id="step-abc",
            step_key="extract",
            status=CustomJobStepStatus.PENDING,
        )

        assert step.run_id == run_id
        assert step.step_index == 0
        assert step.step_id == "step-abc"
        assert step.step_key == "extract"
        assert step.status == CustomJobStepStatus.PENDING
        db_session.add.assert_called_once_with(step)
        db_session.flush.assert_called_once()

    def test_updates_existing_step(self) -> None:
        run_id = uuid4()
        existing_step = SimpleNamespace(
            run_id=run_id,
            step_index=0,
            step_id="step-abc",
            step_key="extract",
            status=CustomJobStepStatus.PENDING,
            started_at=None,
            finished_at=None,
            error_message=None,
            output_json=None,
        )
        db_session = MagicMock()
        db_session.scalar.return_value = existing_step

        result = upsert_run_step(
            db_session=db_session,
            run_id=run_id,
            step_index=0,
            step_id="step-abc",
            step_key="extract",
            status=CustomJobStepStatus.SUCCESS,
            output_json={"count": 10},
        )

        assert result is existing_step
        assert result.status == CustomJobStepStatus.SUCCESS
        assert result.output_json == {"count": 10}
        assert result.finished_at is not None
        # Should NOT call add for existing step.
        db_session.add.assert_not_called()
        db_session.flush.assert_called_once()

    def test_mark_started_sets_started_at(self) -> None:
        run_id = uuid4()
        db_session = MagicMock()
        db_session.scalar.return_value = None

        step = upsert_run_step(
            db_session=db_session,
            run_id=run_id,
            step_index=0,
            step_id="step-start",
            step_key="load",
            status=CustomJobStepStatus.STARTED,
            mark_started=True,
        )

        assert step.started_at is not None

    def test_mark_started_does_not_overwrite_existing(self) -> None:
        original_started = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        existing_step = SimpleNamespace(
            run_id=uuid4(),
            step_index=0,
            step_id="step-xyz",
            step_key="load",
            status=CustomJobStepStatus.STARTED,
            started_at=original_started,
            finished_at=None,
            error_message=None,
            output_json=None,
        )
        db_session = MagicMock()
        db_session.scalar.return_value = existing_step

        upsert_run_step(
            db_session=db_session,
            run_id=existing_step.run_id,
            step_index=0,
            step_id="step-xyz",
            step_key="load",
            status=CustomJobStepStatus.SUCCESS,
            mark_started=True,
        )

        # started_at should remain unchanged.
        assert existing_step.started_at == original_started


class TestCreateTriggerEvent:
    def test_creates_event_successfully(self) -> None:
        job_id = uuid4()
        db_session = MagicMock()
        db_session.begin_nested.return_value = _NoopContextManager()

        event = create_trigger_event(
            db_session=db_session,
            custom_job_id=job_id,
            source_type="webhook",
            source_event_id="evt-123",
            dedupe_key="key-abc",
            dedupe_key_prefix="webhook",
            event_time=datetime.now(timezone.utc),
            payload_json={"data": "value"},
        )

        assert event is not None
        assert event.custom_job_id == job_id
        assert event.source_type == "webhook"
        assert event.dedupe_key == "key-abc"
        assert event.status == CustomJobTriggerEventStatus.RECEIVED
        db_session.add.assert_called_once()
        db_session.flush.assert_called_once()

    def test_returns_none_on_dedupe_integrity_error(self) -> None:
        job_id = uuid4()
        db_session = MagicMock()
        db_session.begin_nested.return_value = _NoopContextManager()
        db_session.flush.side_effect = IntegrityError("stmt", "params", Exception())

        event = create_trigger_event(
            db_session=db_session,
            custom_job_id=job_id,
            source_type="webhook",
            source_event_id="evt-dup",
            dedupe_key="key-dup",
            dedupe_key_prefix=None,
            event_time=None,
            payload_json=None,
        )

        assert event is None


class TestFetchOrCreateTriggerState:
    def test_returns_existing_state(self) -> None:
        job_id = uuid4()
        existing_state = SimpleNamespace(
            custom_job_id=job_id,
            source_key="slack",
            cursor_json={"last_ts": "123"},
        )
        db_session = MagicMock()
        db_session.scalar.return_value = existing_state

        result = fetch_or_create_trigger_state(
            db_session=db_session,
            custom_job_id=job_id,
            source_key="slack",
        )

        assert result is existing_state
        db_session.add.assert_not_called()

    def test_creates_new_state_when_not_found(self) -> None:
        job_id = uuid4()
        db_session = MagicMock()
        db_session.scalar.return_value = None

        result = fetch_or_create_trigger_state(
            db_session=db_session,
            custom_job_id=job_id,
            source_key="gmail",
        )

        assert result.custom_job_id == job_id
        assert result.source_key == "gmail"
        assert result.cursor_json is None
        db_session.add.assert_called_once_with(result)
        db_session.flush.assert_called_once()


class TestComputeNextRunAtDST:
    """DST edge-case tests for compute_next_run_at (items 10 and 11)."""

    def test_spring_forward_nonexistent_time_shifts_to_next_valid(self) -> None:
        # US/Eastern DST spring-forward: March 8, 2026 at 2:00 AM -> 3:00 AM.
        # Scheduling at 2:30 AM local should resolve to 3:00 AM (the gap skip).
        now_utc = datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc)
        next_run = compute_next_run_at(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="US/Eastern",
            hour=2,
            minute=30,
            day_of_week=None,
            now_utc=now_utc,
        )

        assert next_run is not None
        # The result must be stored in UTC and be after the spring-forward gap.
        # 2:30 AM ET doesn't exist on March 8; it should be shifted to 3:00 AM ET
        # which is 7:00 AM UTC.
        assert next_run.tzinfo == timezone.utc
        # After the spring-forward, 3:00 AM ET = 7:00 AM UTC.
        assert next_run >= datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)

    def test_fall_back_ambiguous_time_uses_first_occurrence(self) -> None:
        # US/Eastern DST fall-back: November 1, 2026 at 2:00 AM -> 1:00 AM.
        # 1:00 AM local is ambiguous. fold=0 means first occurrence (EDT, UTC-4).
        now_utc = datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)
        next_run = compute_next_run_at(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="US/Eastern",
            hour=1,
            minute=0,
            day_of_week=None,
            now_utc=now_utc,
        )

        assert next_run is not None
        assert next_run.tzinfo == timezone.utc
        # First occurrence of 1:00 AM ET on Nov 1 is EDT (UTC-4) = 5:00 AM UTC.
        assert next_run == datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)

    def test_non_utc_timezone_stores_utc(self) -> None:
        # Schedule 9:00 AM in America/New_York (EST, UTC-5 in February).
        now_utc = datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc)
        next_run = compute_next_run_at(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="America/New_York",
            hour=9,
            minute=0,
            day_of_week=None,
            now_utc=now_utc,
        )

        assert next_run is not None
        assert next_run.tzinfo == timezone.utc
        # Feb 18 2026, 9:00 AM ET is 2:00 PM UTC (EST = UTC-5).
        # now is 12:00 UTC = 7:00 AM ET, so next 9 AM ET is same day.
        assert next_run == datetime(2026, 2, 18, 14, 0, tzinfo=timezone.utc)

    def test_weekly_non_utc_timezone_stores_utc(self) -> None:
        # Feb 18 2026 is Wednesday. Schedule Monday at 10:00 AM US/Eastern.
        now_utc = datetime(2026, 2, 18, 20, 0, tzinfo=timezone.utc)
        next_run = compute_next_run_at(
            trigger_type=CustomJobTriggerType.WEEKLY,
            timezone_name="US/Eastern",
            hour=10,
            minute=0,
            day_of_week=0,  # Monday
            now_utc=now_utc,
        )

        assert next_run is not None
        assert next_run.tzinfo == timezone.utc
        # Next Monday is Feb 23, 2026. 10:00 AM EST = 15:00 UTC.
        assert next_run == datetime(2026, 2, 23, 15, 0, tzinfo=timezone.utc)
