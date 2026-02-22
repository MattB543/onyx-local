from __future__ import annotations

from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi import Response

from onyx.db.custom_jobs import ManualRunRequestResult
from onyx.db.enums import CustomJobRunStatus
from onyx.db.enums import CustomJobStepStatus
from onyx.db.enums import CustomJobTriggerType
from onyx.server.manage.custom_jobs.api import _ensure_custom_jobs_enabled
from onyx.server.manage.custom_jobs.api import _validate_schedule_fields
from onyx.server.manage.custom_jobs.api import _validate_trigger_source_config
from onyx.server.manage.custom_jobs.api import create_custom_job_endpoint
from onyx.server.manage.custom_jobs.api import delete_custom_job_endpoint
from onyx.server.manage.custom_jobs.api import dry_run_custom_job_endpoint
from onyx.server.manage.custom_jobs.api import get_custom_job_endpoint
from onyx.server.manage.custom_jobs.api import get_custom_job_step_catalog
from onyx.server.manage.custom_jobs.api import list_custom_job_run_steps_endpoint
from onyx.server.manage.custom_jobs.api import list_custom_job_runs_endpoint
from onyx.server.manage.custom_jobs.api import list_custom_jobs_endpoint
from onyx.server.manage.custom_jobs.api import manual_trigger_custom_job_endpoint
from onyx.server.manage.custom_jobs.api import update_custom_job_endpoint
from onyx.server.manage.custom_jobs.models import CustomJobCreateRequest
from onyx.server.manage.custom_jobs.models import CustomJobUpdateRequest
from onyx.custom_jobs.types import WorkflowDefinition


# ---------------------------------------------------------------------------
# Helper to build a fake CustomJob-like object (SimpleNamespace) with all
# fields that CustomJobView.from_model expects.
# ---------------------------------------------------------------------------

def _make_fake_job(**overrides):
    """Return a SimpleNamespace that looks like a CustomJob ORM model."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        name="Test Job",
        workflow_key="weekly_slack_digest",
        enabled=True,
        trigger_type=CustomJobTriggerType.WEEKLY,
        day_of_week=0,
        hour=9,
        minute=0,
        timezone="America/New_York",
        next_run_at=now,
        last_scheduled_at=None,
        trigger_source_type=None,
        trigger_source_config=None,
        job_config={},
        persona_id=None,
        slack_bot_id=None,
        slack_channel_id=None,
        retention_days=90,
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_fake_run(**overrides):
    """Return a SimpleNamespace that looks like a CustomJobRun ORM model."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        custom_job_id=uuid4(),
        status=CustomJobRunStatus.SUCCESS,
        scheduled_for=None,
        trigger_event_id=None,
        idempotency_key=None,
        started_at=now,
        finished_at=now,
        error_message=None,
        metrics_json=None,
        output_preview=None,
        created_at=now,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_fake_step(**overrides):
    """Return a SimpleNamespace that looks like a CustomJobRunStep ORM model."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        run_id=uuid4(),
        step_index=0,
        step_id="fetch_content",
        step_key="fetch_weekly_chat_content",
        status=CustomJobStepStatus.SUCCESS,
        started_at=now,
        finished_at=now,
        error_message=None,
        output_json=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_validate_trigger_source_config_rejects_short_poll_interval() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_trigger_source_config(
            trigger_type=CustomJobTriggerType.TRIGGERED,
            trigger_source_config={"poll_interval_seconds": 59},
        )

    assert exc.value.status_code == 400
    assert "poll_interval_seconds" in str(exc.value.detail)


def test_validate_trigger_source_config_rejects_non_positive_limits() -> None:
    with pytest.raises(HTTPException):
        _validate_trigger_source_config(
            trigger_type=CustomJobTriggerType.TRIGGERED,
            trigger_source_config={"max_events_per_claim": 0},
        )

    with pytest.raises(HTTPException):
        _validate_trigger_source_config(
            trigger_type=CustomJobTriggerType.TRIGGERED,
            trigger_source_config={"max_concurrent_runs": 0},
        )


def test_validate_trigger_source_config_is_noop_for_non_triggered_jobs() -> None:
    _validate_trigger_source_config(
        trigger_type=CustomJobTriggerType.WEEKLY,
        trigger_source_config={"poll_interval_seconds": 1},
    )


def test_manual_trigger_returns_deduplicated_without_enqueue() -> None:
    job_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        status=CustomJobRunStatus.PENDING,
        error_message=None,
        finished_at=None,
    )
    manual_result = ManualRunRequestResult(run=run, created=False)
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch(
            "onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=SimpleNamespace(id=job_id, enabled=True),
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.create_manual_run_if_allowed",
            return_value=manual_result,
        ) as mock_create_manual,
        patch("onyx.server.manage.custom_jobs.api.add_custom_job_audit_log"),
        patch("onyx.server.manage.custom_jobs.api.client_app.send_task") as mock_send_task,
        patch("onyx.server.manage.custom_jobs.api.get_current_tenant_id", return_value="public"),
    ):
        response = manual_trigger_custom_job_endpoint(
            job_id=job_id,
            idempotency_key="idem-abc",
            user=user,
            db_session=db_session,
        )

    assert response.run_id == run.id
    assert response.status == "deduplicated"
    mock_create_manual.assert_called_once()
    assert mock_create_manual.call_args.kwargs["idempotency_key"] == "idem-abc"
    mock_send_task.assert_not_called()


def test_manual_trigger_queues_new_run() -> None:
    job_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        status=CustomJobRunStatus.PENDING,
        error_message=None,
        finished_at=None,
    )
    manual_result = ManualRunRequestResult(run=run, created=True)
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=SimpleNamespace(id=job_id, enabled=True),
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.create_manual_run_if_allowed",
            return_value=manual_result,
        ),
        patch("onyx.server.manage.custom_jobs.api.add_custom_job_audit_log"),
        patch("onyx.server.manage.custom_jobs.api.client_app.send_task") as mock_send_task,
        patch("onyx.server.manage.custom_jobs.api.get_current_tenant_id", return_value="public"),
    ):
        response = manual_trigger_custom_job_endpoint(
            job_id=job_id,
            idempotency_key="idem-xyz",
            user=user,
            db_session=db_session,
        )

    assert response.run_id == run.id
    assert response.status == "queued"
    mock_send_task.assert_called_once()
    assert mock_send_task.call_args.kwargs["kwargs"]["run_id"] == str(run.id)
    assert mock_send_task.call_args.kwargs["kwargs"]["tenant_id"] == "public"


def test_manual_trigger_marks_run_failed_if_enqueue_errors() -> None:
    job_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        status=CustomJobRunStatus.PENDING,
        error_message=None,
        finished_at=None,
    )
    manual_result = ManualRunRequestResult(run=run, created=True)
    db_session = MagicMock()
    db_session.scalar.return_value = run
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=SimpleNamespace(id=job_id, enabled=True),
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.create_manual_run_if_allowed",
            return_value=manual_result,
        ),
        patch("onyx.server.manage.custom_jobs.api.add_custom_job_audit_log"),
        patch(
            "onyx.server.manage.custom_jobs.api.client_app.send_task",
            side_effect=RuntimeError("redis down"),
        ),
        patch("onyx.server.manage.custom_jobs.api.get_current_tenant_id", return_value="public"),
    ):
        with pytest.raises(HTTPException) as exc:
            manual_trigger_custom_job_endpoint(
                job_id=job_id,
                idempotency_key=None,
                user=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 500
    assert run.status == CustomJobRunStatus.FAILURE
    assert "Failed to enqueue custom job run" in str(run.error_message)
    assert run.finished_at is not None


def test_dry_run_reports_invalid_trigger_source_config() -> None:
    job = SimpleNamespace(
        id=uuid4(),
        trigger_type=CustomJobTriggerType.TRIGGERED,
        trigger_source_config={"poll_interval_seconds": 30},
        trigger_source_type="google_drive",
        workflow_key="wf-key",
        job_config={},
        timezone=None,
        hour=None,
        minute=None,
        day_of_week=None,
    )
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch("onyx.server.manage.custom_jobs.api.fetch_custom_job", return_value=job),
        patch(
            "onyx.server.manage.custom_jobs.api._validate_workflow_and_step_configs",
            return_value=WorkflowDefinition(workflow_key="wf-key", steps=[]),
        ),
        patch(
            "onyx.server.manage.custom_jobs.api._dry_run_integration_checks",
            return_value=[],
        ),
    ):
        response = dry_run_custom_job_endpoint(
            job_id=job.id,
            user=user,
            db_session=db_session,
        )

    assert response.valid is False
    assert any("poll_interval_seconds" in err for err in response.errors)


# ---------------------------------------------------------------------------
# 1. GET / — list_custom_jobs_endpoint
# ---------------------------------------------------------------------------

def test_list_jobs_returns_all_jobs() -> None:
    job1 = _make_fake_job(name="Job A")
    job2 = _make_fake_job(name="Job B")
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.list_custom_jobs",
            return_value=[job1, job2],
        ) as mock_list,
    ):
        result = list_custom_jobs_endpoint(
            enabled=None,
            _=user,
            db_session=db_session,
        )

    assert len(result) == 2
    assert result[0].name == "Job A"
    assert result[1].name == "Job B"
    mock_list.assert_called_once_with(db_session=db_session, enabled=None)


def test_list_jobs_filters_by_enabled() -> None:
    job1 = _make_fake_job(name="Enabled Job", enabled=True)
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.list_custom_jobs",
            return_value=[job1],
        ) as mock_list,
    ):
        result = list_custom_jobs_endpoint(
            enabled=True,
            _=user,
            db_session=db_session,
        )

    assert len(result) == 1
    mock_list.assert_called_once_with(db_session=db_session, enabled=True)


def test_list_jobs_returns_empty_list() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.list_custom_jobs",
            return_value=[],
        ),
    ):
        result = list_custom_jobs_endpoint(
            enabled=None,
            _=user,
            db_session=db_session,
        )

    assert result == []


# ---------------------------------------------------------------------------
# 2. POST / — create_custom_job_endpoint
# ---------------------------------------------------------------------------

def test_create_job_weekly_with_valid_config() -> None:
    user = SimpleNamespace(id=uuid4())
    db_session = MagicMock()
    next_run = datetime(2025, 1, 6, 14, 0, tzinfo=timezone.utc)

    request = CustomJobCreateRequest(
        name="Weekly Digest",
        workflow_key="weekly_slack_digest",
        enabled=True,
        trigger_type=CustomJobTriggerType.WEEKLY,
        day_of_week=0,
        hour=9,
        minute=0,
        timezone="America/New_York",
    )

    # We need to capture the CustomJob object that gets added to the session
    captured_job = {}

    def fake_add(obj):
        # Populate the object with fields CustomJobView.from_model needs
        obj.id = uuid4()
        obj.created_at = datetime.now(timezone.utc)
        obj.updated_at = datetime.now(timezone.utc)
        obj.last_scheduled_at = None
        captured_job["obj"] = obj

    db_session.add.side_effect = fake_add
    db_session.refresh.side_effect = lambda obj: None

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api._validate_workflow_and_step_configs",
            return_value=WorkflowDefinition(workflow_key="weekly_slack_digest", steps=[]),
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.compute_next_run_at",
            return_value=next_run,
        ) as mock_compute,
        patch("onyx.server.manage.custom_jobs.api.add_custom_job_audit_log"),
        patch("onyx.server.manage.custom_jobs.api.get_current_tenant_id", return_value="public"),
    ):
        result = create_custom_job_endpoint(
            request=request,
            user=user,
            db_session=db_session,
        )

    db_session.add.assert_called_once()
    db_session.flush.assert_called_once()
    db_session.commit.assert_called_once()
    mock_compute.assert_called_once()

    assert result.name == "Weekly Digest"
    assert result.workflow_key == "weekly_slack_digest"
    assert result.trigger_type == CustomJobTriggerType.WEEKLY
    assert result.next_run_at == next_run


def test_create_job_triggered_clears_schedule_fields() -> None:
    user = SimpleNamespace(id=uuid4())
    db_session = MagicMock()

    request = CustomJobCreateRequest(
        name="Event-driven Job",
        workflow_key="weekly_slack_digest",
        enabled=True,
        trigger_type=CustomJobTriggerType.TRIGGERED,
        hour=9,
        minute=0,
        timezone="America/New_York",
    )

    captured_job = {}

    def fake_add(obj):
        obj.id = uuid4()
        obj.created_at = datetime.now(timezone.utc)
        obj.updated_at = datetime.now(timezone.utc)
        obj.last_scheduled_at = None
        captured_job["obj"] = obj

    db_session.add.side_effect = fake_add
    db_session.refresh.side_effect = lambda obj: None

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api._validate_workflow_and_step_configs",
            return_value=WorkflowDefinition(workflow_key="weekly_slack_digest", steps=[]),
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.compute_next_run_at",
            return_value=None,
        ),
        patch("onyx.server.manage.custom_jobs.api.add_custom_job_audit_log"),
        patch("onyx.server.manage.custom_jobs.api.get_current_tenant_id", return_value="public"),
    ):
        result = create_custom_job_endpoint(
            request=request,
            user=user,
            db_session=db_session,
        )

    # For triggered jobs, schedule fields should be cleared to None
    job = captured_job["obj"]
    assert job.hour is None
    assert job.minute is None
    assert job.timezone is None
    assert job.day_of_week is None
    assert result.next_run_at is None


# ---------------------------------------------------------------------------
# 3. GET /{job_id} — get_custom_job_endpoint
# ---------------------------------------------------------------------------

def test_get_job_found() -> None:
    job = _make_fake_job(name="My Job")
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=job,
        ),
    ):
        result = get_custom_job_endpoint(
            job_id=job.id,
            _=user,
            db_session=db_session,
        )

    assert result.id == job.id
    assert result.name == "My Job"


def test_get_job_not_found() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=None,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            get_custom_job_endpoint(
                job_id=uuid4(),
                _=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 4. PATCH /{job_id} — update_custom_job_endpoint
# ---------------------------------------------------------------------------

def test_update_job_schedule_triggers_next_run_recompute() -> None:
    job = _make_fake_job()
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())
    new_next_run = datetime(2025, 2, 3, 15, 0, tzinfo=timezone.utc)

    request = CustomJobUpdateRequest(hour=15)

    db_session.refresh.side_effect = lambda obj: None

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=job,
        ),
        patch(
            "onyx.server.manage.custom_jobs.api._validate_workflow_and_step_configs",
            return_value=WorkflowDefinition(workflow_key=job.workflow_key, steps=[]),
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.compute_next_run_at",
            return_value=new_next_run,
        ) as mock_compute,
        patch("onyx.server.manage.custom_jobs.api.add_custom_job_audit_log"),
        patch("onyx.server.manage.custom_jobs.api.get_current_tenant_id", return_value="public"),
    ):
        result = update_custom_job_endpoint(
            job_id=job.id,
            request=request,
            user=user,
            db_session=db_session,
        )

    mock_compute.assert_called_once()
    # The compute should have been called with the new hour value
    call_kwargs = mock_compute.call_args.kwargs
    assert call_kwargs["hour"] == 15
    assert job.next_run_at == new_next_run


def test_update_job_not_found() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())
    request = CustomJobUpdateRequest(name="Updated Name")

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=None,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            update_custom_job_endpoint(
                job_id=uuid4(),
                request=request,
                user=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 404


def test_update_job_no_changes_returns_current() -> None:
    job = _make_fake_job()
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    # Empty update (no fields set)
    request = CustomJobUpdateRequest()

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=job,
        ),
    ):
        result = update_custom_job_endpoint(
            job_id=job.id,
            request=request,
            user=user,
            db_session=db_session,
        )

    # Should return current job without committing
    assert result.id == job.id
    db_session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 5. DELETE /{job_id} — delete_custom_job_endpoint
# ---------------------------------------------------------------------------

def test_delete_job_success() -> None:
    job = _make_fake_job()
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=job,
        ),
        patch("onyx.server.manage.custom_jobs.api.get_current_tenant_id", return_value="public"),
    ):
        result = delete_custom_job_endpoint(
            job_id=job.id,
            user=user,
            db_session=db_session,
        )

    assert isinstance(result, Response)
    assert result.status_code == 204
    db_session.delete.assert_called_once_with(job)
    db_session.commit.assert_called_once()


def test_delete_job_not_found() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=None,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            delete_custom_job_endpoint(
                job_id=uuid4(),
                user=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 6. GET /{job_id}/runs — list_custom_job_runs_endpoint
# ---------------------------------------------------------------------------

def test_list_runs_passes_pagination_and_filters() -> None:
    job = _make_fake_job()
    run1 = _make_fake_run(custom_job_id=job.id)
    run2 = _make_fake_run(custom_job_id=job.id)
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=job,
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.list_custom_job_runs",
            return_value=([run1, run2], 2),
        ) as mock_list_runs,
    ):
        result = list_custom_job_runs_endpoint(
            job_id=job.id,
            page=1,
            page_size=10,
            status=None,
            started_after=None,
            started_before=None,
            sort="-started_at",
            _=user,
            db_session=db_session,
        )

    assert result.total_items == 2
    assert len(result.items) == 2
    mock_list_runs.assert_called_once()
    call_kwargs = mock_list_runs.call_args.kwargs
    assert call_kwargs["page"] == 1
    assert call_kwargs["page_size"] == 10


def test_list_runs_status_filter() -> None:
    job = _make_fake_job()
    run1 = _make_fake_run(custom_job_id=job.id, status=CustomJobRunStatus.FAILURE)
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=job,
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.list_custom_job_runs",
            return_value=([run1], 1),
        ) as mock_list_runs,
    ):
        result = list_custom_job_runs_endpoint(
            job_id=job.id,
            page=0,
            page_size=20,
            status=CustomJobRunStatus.FAILURE,
            started_after=None,
            started_before=None,
            sort="-started_at",
            _=user,
            db_session=db_session,
        )

    assert result.total_items == 1
    filters = mock_list_runs.call_args.kwargs["filters"]
    assert filters.status == CustomJobRunStatus.FAILURE


def test_list_runs_job_not_found() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=None,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            list_custom_job_runs_endpoint(
                job_id=uuid4(),
                page=0,
                page_size=20,
                status=None,
                started_after=None,
                started_before=None,
                sort="-started_at",
                _=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 404


def test_list_runs_invalid_sort() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
    ):
        with pytest.raises(HTTPException) as exc:
            list_custom_job_runs_endpoint(
                job_id=uuid4(),
                page=0,
                page_size=20,
                status=None,
                started_after=None,
                started_before=None,
                sort="invalid_sort",
                _=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 400
    assert "Invalid sort" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# 7. GET /{job_id}/runs/{run_id}/steps — list_custom_job_run_steps_endpoint
# ---------------------------------------------------------------------------

def test_list_steps_returns_steps_for_run() -> None:
    job_id = uuid4()
    run_id = uuid4()
    step1 = _make_fake_step(run_id=run_id, step_index=0, step_id="step_a")
    step2 = _make_fake_step(run_id=run_id, step_index=1, step_id="step_b")
    db_session = MagicMock()
    # The endpoint does db_session.scalar() to fetch the run
    fake_run = SimpleNamespace(id=run_id, custom_job_id=job_id)
    db_session.scalar.return_value = fake_run
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.list_custom_job_run_steps",
            return_value=([step1, step2], 2),
        ) as mock_list_steps,
    ):
        result = list_custom_job_run_steps_endpoint(
            job_id=job_id,
            run_id=run_id,
            page=0,
            page_size=50,
            _=user,
            db_session=db_session,
        )

    assert result.total_items == 2
    assert len(result.items) == 2
    assert result.items[0].step_id == "step_a"
    assert result.items[1].step_id == "step_b"
    mock_list_steps.assert_called_once_with(
        db_session=db_session,
        run_id=run_id,
        page=0,
        page_size=50,
    )


def test_list_steps_run_not_found() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
    ):
        with pytest.raises(HTTPException) as exc:
            list_custom_job_run_steps_endpoint(
                job_id=uuid4(),
                run_id=uuid4(),
                page=0,
                page_size=50,
                _=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 404
    assert "Run not found" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# 8. GET /step-catalog — get_custom_job_step_catalog
# ---------------------------------------------------------------------------

def test_step_catalog_returns_items_with_keys_and_schemas() -> None:
    catalog_items = [
        {
            "step_key": "fetch_weekly_chat_content",
            "description": "Fetches chat content",
            "config_schema": {"type": "object", "properties": {"window_days": {"type": "integer"}}},
        },
        {
            "step_key": "summarize_weekly_content",
            "description": "Summarizes content",
            "config_schema": {"type": "object"},
        },
    ]
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.get_step_catalog",
            return_value=catalog_items,
        ),
    ):
        result = get_custom_job_step_catalog(_=user)

    assert len(result) == 2
    assert result[0].step_key == "fetch_weekly_chat_content"
    assert result[0].description == "Fetches chat content"
    assert "properties" in result[0].config_schema
    assert result[1].step_key == "summarize_weekly_content"


# ---------------------------------------------------------------------------
# 9. Feature gate — _ensure_custom_jobs_enabled
# ---------------------------------------------------------------------------

def test_feature_gate_disabled_raises_400() -> None:
    with patch("onyx.server.manage.custom_jobs.api.ENABLE_CUSTOM_JOBS", False):
        with pytest.raises(HTTPException) as exc:
            _ensure_custom_jobs_enabled()

    assert exc.value.status_code == 400
    assert "disabled" in str(exc.value.detail).lower()


def test_feature_gate_enabled_does_not_raise() -> None:
    with patch("onyx.server.manage.custom_jobs.api.ENABLE_CUSTOM_JOBS", True):
        _ensure_custom_jobs_enabled()


def test_list_jobs_blocked_when_feature_disabled() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with patch("onyx.server.manage.custom_jobs.api.ENABLE_CUSTOM_JOBS", False):
        with pytest.raises(HTTPException) as exc:
            list_custom_jobs_endpoint(
                enabled=None,
                _=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 400


def test_get_job_blocked_when_feature_disabled() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with patch("onyx.server.manage.custom_jobs.api.ENABLE_CUSTOM_JOBS", False):
        with pytest.raises(HTTPException) as exc:
            get_custom_job_endpoint(
                job_id=uuid4(),
                _=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 400


def test_delete_job_blocked_when_feature_disabled() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with patch("onyx.server.manage.custom_jobs.api.ENABLE_CUSTOM_JOBS", False):
        with pytest.raises(HTTPException) as exc:
            delete_custom_job_endpoint(
                job_id=uuid4(),
                user=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 10. Manual trigger cooldown — 409 when triggering within 60s
# ---------------------------------------------------------------------------

def test_manual_trigger_cooldown_returns_409() -> None:
    job_id = uuid4()
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=SimpleNamespace(id=job_id, enabled=True),
        ),
        patch(
            "onyx.server.manage.custom_jobs.api.create_manual_run_if_allowed",
            side_effect=ValueError("Manual trigger cooldown active (60s). Try again later."),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            manual_trigger_custom_job_endpoint(
                job_id=job_id,
                idempotency_key=None,
                user=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 409
    assert "cooldown" in str(exc.value.detail).lower()


# ---------------------------------------------------------------------------
# 11. Disabled job rejection
# ---------------------------------------------------------------------------

def test_manual_trigger_disabled_job_returns_400() -> None:
    job_id = uuid4()
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=SimpleNamespace(id=job_id, enabled=False),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            manual_trigger_custom_job_endpoint(
                job_id=job_id,
                idempotency_key=None,
                user=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 400
    assert "disabled" in str(exc.value.detail).lower()


def test_manual_trigger_job_not_found() -> None:
    db_session = MagicMock()
    user = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.manage.custom_jobs.api._ensure_custom_jobs_enabled"),
        patch(
            "onyx.server.manage.custom_jobs.api.fetch_custom_job",
            return_value=None,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            manual_trigger_custom_job_endpoint(
                job_id=uuid4(),
                idempotency_key=None,
                user=user,
                db_session=db_session,
            )

    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 12. Schedule validation — _validate_schedule_fields
# ---------------------------------------------------------------------------

def test_schedule_validation_hour_out_of_range() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_fields(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="UTC",
            hour=25,
            minute=0,
            day_of_week=None,
        )

    assert exc.value.status_code == 400
    assert "hour" in str(exc.value.detail).lower()


def test_schedule_validation_negative_hour() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_fields(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="UTC",
            hour=-1,
            minute=0,
            day_of_week=None,
        )

    assert exc.value.status_code == 400


def test_schedule_validation_minute_out_of_range() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_fields(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="UTC",
            hour=9,
            minute=60,
            day_of_week=None,
        )

    assert exc.value.status_code == 400
    assert "minute" in str(exc.value.detail).lower()


def test_schedule_validation_missing_timezone() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_fields(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name=None,
            hour=9,
            minute=0,
            day_of_week=None,
        )

    assert exc.value.status_code == 400
    assert "timezone" in str(exc.value.detail).lower()


def test_schedule_validation_missing_hour() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_fields(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="UTC",
            hour=None,
            minute=0,
            day_of_week=None,
        )

    assert exc.value.status_code == 400


def test_schedule_validation_invalid_timezone() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_fields(
            trigger_type=CustomJobTriggerType.DAILY,
            timezone_name="Not/A/Real/Timezone",
            hour=9,
            minute=0,
            day_of_week=None,
        )

    assert exc.value.status_code == 400
    assert "timezone" in str(exc.value.detail).lower()


def test_schedule_validation_weekly_missing_day_of_week() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_fields(
            trigger_type=CustomJobTriggerType.WEEKLY,
            timezone_name="UTC",
            hour=9,
            minute=0,
            day_of_week=None,
        )

    assert exc.value.status_code == 400
    assert "day_of_week" in str(exc.value.detail).lower()


def test_schedule_validation_weekly_day_out_of_range() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_fields(
            trigger_type=CustomJobTriggerType.WEEKLY,
            timezone_name="UTC",
            hour=9,
            minute=0,
            day_of_week=7,
        )

    assert exc.value.status_code == 400
    assert "day_of_week" in str(exc.value.detail).lower()


def test_schedule_validation_triggered_skips_all_checks() -> None:
    # Should not raise even with all-None schedule fields
    _validate_schedule_fields(
        trigger_type=CustomJobTriggerType.TRIGGERED,
        timezone_name=None,
        hour=None,
        minute=None,
        day_of_week=None,
    )


def test_schedule_validation_valid_daily() -> None:
    # Should not raise
    _validate_schedule_fields(
        trigger_type=CustomJobTriggerType.DAILY,
        timezone_name="UTC",
        hour=23,
        minute=59,
        day_of_week=None,
    )


def test_schedule_validation_valid_weekly() -> None:
    # Should not raise
    _validate_schedule_fields(
        trigger_type=CustomJobTriggerType.WEEKLY,
        timezone_name="America/New_York",
        hour=0,
        minute=0,
        day_of_week=6,
    )
