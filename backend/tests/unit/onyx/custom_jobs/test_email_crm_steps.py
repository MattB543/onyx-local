from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.custom_jobs.steps.fetch_email_trigger_payload import (
    FetchEmailTriggerPayloadStep,
)
from onyx.custom_jobs.steps.process_email_crm import ProcessEmailCrmStep
from onyx.custom_jobs.types import StepContext
from onyx.db.enums import CustomJobStepStatus


def _context(
    *,
    step_config: dict | None = None,
    previous_outputs: dict | None = None,
    db_session: MagicMock | None = None,
) -> StepContext:
    return StepContext(
        db_session=db_session or MagicMock(),
        tenant_id="public",
        run_id=uuid4(),
        job_id=uuid4(),
        job_config={},
        step_config=step_config or {},
        previous_outputs=previous_outputs or {},
        deadline_monotonic=1_000_000.0,
    )


def test_fetch_email_trigger_payload_skips_when_run_missing() -> None:
    step = FetchEmailTriggerPayloadStep()
    db_session = MagicMock()
    db_session.scalar.return_value = None

    result = step.run(_context(db_session=db_session))

    assert result.status == CustomJobStepStatus.SKIPPED
    assert "Run not found" in str(result.error_message)


def test_fetch_email_trigger_payload_skips_when_trigger_event_missing() -> None:
    step = FetchEmailTriggerPayloadStep()
    run = SimpleNamespace(trigger_event=None)
    db_session = MagicMock()
    db_session.scalar.return_value = run

    result = step.run(_context(db_session=db_session))

    assert result.status == CustomJobStepStatus.SKIPPED
    assert "No trigger event associated" in str(result.error_message)


def test_fetch_email_trigger_payload_skips_when_required_fields_missing() -> None:
    step = FetchEmailTriggerPayloadStep()
    trigger_event = SimpleNamespace(
        id=uuid4(),
        payload_json={
            "document_id": "doc-1",
            "source": "imap",
            # missing semantic_identifier / primary_owner_emails / text
        },
    )
    run = SimpleNamespace(trigger_event=trigger_event)
    db_session = MagicMock()
    db_session.scalar.return_value = run

    result = step.run(_context(db_session=db_session))

    assert result.status == CustomJobStepStatus.SKIPPED
    assert "missing required fields" in str(result.error_message).lower()


def test_fetch_email_trigger_payload_normalizes_legacy_payload_shape() -> None:
    step = FetchEmailTriggerPayloadStep()
    trigger_event = SimpleNamespace(
        id=uuid4(),
        payload_json={
            "document_id": "doc-2",
            "source": "gmail",
            "semantic_identifier": "Renewal Request",
            "doc_updated_at": "2026-02-20T15:30:00+00:00",
            "primary_owner_emails": ["alice@example.com"],
            "secondary_owner_emails": ["sales@example.com"],
            "text": "Please help with renewal details.",
        },
    )
    run = SimpleNamespace(trigger_event=trigger_event)
    db_session = MagicMock()
    db_session.scalar.return_value = run

    result = step.run(_context(db_session=db_session))

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert result.output_json["from"] == "alice@example.com"
    assert result.output_json["to"] == "sales@example.com"
    assert result.output_json["subject"] == "Renewal Request"
    assert result.output_json["date"] == "2026-02-20T15:30:00+00:00"
    assert result.output_json["body"] == "Please help with renewal details."
    assert result.output_json["text"] == "Please help with renewal details."


def test_fetch_email_trigger_payload_preserves_explicit_prompt_fields() -> None:
    step = FetchEmailTriggerPayloadStep()
    trigger_event = SimpleNamespace(
        id=uuid4(),
        payload_json={
            "document_id": "doc-3",
            "source": "imap",
            "semantic_identifier": "Fallback subject",
            "primary_owner_emails": ["fallback@example.com"],
            "secondary_owner_emails": ["recipient@example.com"],
            "text": "fallback body",
            "from": "Alice <alice@example.com>",
            "to": "Bob <bob@example.com>",
            "subject": "Explicit Subject",
            "date": "2026-01-02T03:04:05+00:00",
            "body": "Explicit body",
        },
    )
    run = SimpleNamespace(trigger_event=trigger_event)
    db_session = MagicMock()
    db_session.scalar.return_value = run

    result = step.run(_context(db_session=db_session))

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert result.output_json["from"] == "Alice <alice@example.com>"
    assert result.output_json["to"] == "Bob <bob@example.com>"
    assert result.output_json["subject"] == "Explicit Subject"
    assert result.output_json["date"] == "2026-01-02T03:04:05+00:00"
    assert result.output_json["body"] == "Explicit body"


def test_process_email_crm_fails_when_persona_id_missing() -> None:
    step = ProcessEmailCrmStep()
    result = step.run(
        _context(previous_outputs={"fetch_email_trigger_payload": {"body": "x"}})
    )
    assert result.status == CustomJobStepStatus.FAILURE
    assert "persona_id is not configured" in str(result.error_message)


def test_process_email_crm_fails_when_persona_id_invalid() -> None:
    step = ProcessEmailCrmStep()
    result = step.run(
        _context(
            step_config={"persona_id": "abc"},
            previous_outputs={"fetch_email_trigger_payload": {"body": "x"}},
        )
    )
    assert result.status == CustomJobStepStatus.FAILURE
    assert "persona_id must be an integer" in str(result.error_message)


def test_process_email_crm_fails_when_input_step_output_missing() -> None:
    step = ProcessEmailCrmStep()
    result = step.run(_context(step_config={"persona_id": 42}, previous_outputs={}))
    assert result.status == CustomJobStepStatus.FAILURE
    assert "Missing required step output" in str(result.error_message)


def test_process_email_crm_fails_when_chat_pipeline_raises() -> None:
    step = ProcessEmailCrmStep()
    context = _context(
        step_config={"persona_id": 42},
        previous_outputs={
            "fetch_email_trigger_payload": {
                "from": "alice@example.com",
                "to": "sales@example.com",
                "subject": "Subject",
                "date": "2026-01-01T00:00:00+00:00",
                "body": "Body",
            }
        },
    )

    with patch(
        "onyx.custom_jobs.steps.process_email_crm.handle_stream_message_objects",
        side_effect=RuntimeError("boom"),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.FAILURE
    assert "Chat pipeline raised an exception" in str(result.error_message)


def test_process_email_crm_fails_when_chat_pipeline_returns_error() -> None:
    step = ProcessEmailCrmStep()
    context = _context(
        step_config={"persona_id": 42},
        previous_outputs={
            "fetch_email_trigger_payload": {
                "from": "alice@example.com",
                "to": "sales@example.com",
                "subject": "Subject",
                "date": "2026-01-01T00:00:00+00:00",
                "body": "Body",
            }
        },
    )

    with (
        patch(
            "onyx.custom_jobs.steps.process_email_crm.handle_stream_message_objects",
            return_value=["packet"],
        ),
        patch(
            "onyx.custom_jobs.steps.process_email_crm.gather_stream_full",
            return_value=SimpleNamespace(error_msg="tool failed"),
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.FAILURE
    assert "Chat pipeline returned an error" in str(result.error_message)


def test_process_email_crm_success_uses_context_db_session_and_legacy_fallbacks() -> None:
    step = ProcessEmailCrmStep()
    context = _context(
        step_config={"persona_id": 123},
        previous_outputs={
            # Legacy payload shape from trigger event.
            "fetch_email_trigger_payload": {
                "semantic_identifier": "Renewal Request",
                "doc_updated_at": "2026-02-20T15:30:00+00:00",
                "primary_owner_emails": ["alice@example.com"],
                "secondary_owner_emails": ["sales@example.com"],
                "text": "Can we renew next quarter?",
            }
        },
    )
    fake_user = SimpleNamespace(id="user-1", is_anonymous=True)
    fake_response = SimpleNamespace(
        error_msg=None,
        answer="Done",
        tool_calls=[
            SimpleNamespace(
                tool_name="crm_search",
                tool_arguments={"query": "alice@example.com"},
                tool_result={"status": "ok"},
            )
        ],
        chat_session_id=uuid4(),
        message_id=321,
    )

    with (
        patch(
            "onyx.custom_jobs.steps.process_email_crm.get_anonymous_user",
            return_value=fake_user,
        ),
        patch(
            "onyx.custom_jobs.steps.process_email_crm.handle_stream_message_objects",
            return_value=["packet"],
        ) as mock_handle,
        patch(
            "onyx.custom_jobs.steps.process_email_crm.gather_stream_full",
            return_value=fake_response,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert result.output_json["answer"] == "Done"
    assert result.output_json["tool_call_count"] == 1
    assert result.output_json["message_id"] == 321

    handle_kwargs = mock_handle.call_args.kwargs
    assert handle_kwargs["db_session"] is context.db_session
    assert handle_kwargs["user"] is fake_user
    assert handle_kwargs["bypass_acl"] is True

    req = handle_kwargs["new_msg_req"]
    assert "From: alice@example.com" in req.message
    assert "To: sales@example.com" in req.message
    assert "Subject: Renewal Request" in req.message
    assert "Date: 2026-02-20T15:30:00+00:00" in req.message
    assert "Can we renew next quarter?" in req.message
    assert req.chat_session_info is not None
    assert req.chat_session_info.persona_id == 123
