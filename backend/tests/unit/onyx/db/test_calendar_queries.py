from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from onyx.db.calendar import search_calendar_events


def _make_doc(
    *,
    doc_id: str = "google_calendar:primary:evt-1",
    semantic_id: str = "Team Sync",
    metadata: dict | None = None,
):
    return SimpleNamespace(
        id=doc_id,
        semantic_id=semantic_id,
        doc_metadata=metadata
        or {
            "calendar_id": "primary",
            "calendar_name": "Primary",
            "event_status": "confirmed",
            "start_time_utc": "2026-02-20T17:00:00+00:00",
            "end_time_utc": "2026-02-20T17:30:00+00:00",
            "event_timezone": "UTC",
            "is_all_day": "false",
            "organizer_email": "owner@example.com",
            "attendee_emails": ["owner@example.com", "teammate@example.com"],
            "location": "Zoom",
            "meeting_url": "https://meet.google.com/abc-defg-hij",
            "event_url": "https://calendar.google.com/event?eid=abc123",
        },
        link="https://calendar.google.com/event?eid=abc123",
        doc_updated_at=datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc),
    )


def _prepare_db_session(total_items: int, docs: list[SimpleNamespace]) -> MagicMock:
    db_session = MagicMock()
    db_session.scalar.return_value = total_items
    scalar_result = MagicMock()
    scalar_result.all.return_value = docs
    db_session.scalars.return_value = scalar_result
    return db_session


def test_search_calendar_events_applies_time_window_and_pagination_in_sql() -> None:
    db_session = _prepare_db_session(total_items=1, docs=[_make_doc()])
    window_start = datetime(2026, 2, 20, 0, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 2, 21, 0, 0, tzinfo=timezone.utc)

    results, total = search_calendar_events(
        db_session=db_session,
        query=None,
        start_time=window_start,
        end_time=window_end,
        organizer_email=None,
        attendee_emails=None,
        calendar_ids=None,
        event_statuses=None,
        include_all_day=None,
        creator_id=uuid4(),
        page_num=0,
        page_size=10,
        sort_by="start_time",
        sort_order="asc",
    )

    assert total == 1
    assert len(results) == 1

    paged_stmt = db_session.scalars.call_args.args[0]
    compiled = paged_stmt.compile()
    params = compiled.params.values()
    assert window_start.isoformat() in params
    assert window_end.isoformat() in params


def test_search_calendar_events_escapes_like_query() -> None:
    db_session = _prepare_db_session(total_items=0, docs=[])
    query = "team_sync%q1"
    expected_like = "%team\\_sync\\%q1%"

    search_calendar_events(
        db_session=db_session,
        query=query,
        start_time=None,
        end_time=None,
        organizer_email=None,
        attendee_emails=None,
        calendar_ids=None,
        event_statuses=None,
        include_all_day=None,
        creator_id=None,
        page_num=0,
        page_size=10,
        sort_by="start_time",
        sort_order="asc",
    )

    paged_stmt = db_session.scalars.call_args.args[0]
    compiled = paged_stmt.compile()
    assert expected_like in compiled.params.values()


def test_search_calendar_events_applies_identity_and_attendee_filters() -> None:
    db_session = _prepare_db_session(total_items=0, docs=[])

    search_calendar_events(
        db_session=db_session,
        query=None,
        start_time=None,
        end_time=None,
        organizer_email=" Owner@Example.com ",
        attendee_emails=[" attendee@example.com "],
        calendar_ids=[" Primary "],
        event_statuses=["Confirmed"],
        include_all_day=False,
        creator_id=uuid4(),
        page_num=0,
        page_size=25,
        sort_by="updated_at",
        sort_order="desc",
    )

    paged_stmt = db_session.scalars.call_args.args[0]
    compiled = paged_stmt.compile()
    params = set(str(v) for v in compiled.params.values())
    assert "owner@example.com" in params
    assert any("primary" in param for param in params)
    assert any("confirmed" in param for param in params)
    assert "false" in params
    assert any("attendee@example.com" in param for param in params)


def test_search_calendar_events_desc_sort_keeps_ascending_tiebreakers() -> None:
    db_session = _prepare_db_session(total_items=0, docs=[])

    search_calendar_events(
        db_session=db_session,
        query="team",
        start_time=None,
        end_time=None,
        organizer_email=None,
        attendee_emails=None,
        calendar_ids=None,
        event_statuses=None,
        include_all_day=None,
        creator_id=None,
        page_num=0,
        page_size=25,
        sort_by="start_time",
        sort_order="desc",
    )

    paged_stmt = db_session.scalars.call_args.args[0]
    compiled_sql = str(paged_stmt.compile()).lower()
    assert "desc" in compiled_sql
    assert "semantic_id" in compiled_sql
    assert "document.id" in compiled_sql


def test_search_calendar_events_parses_metadata_resiliently() -> None:
    db_session = _prepare_db_session(
        total_items=1,
        docs=[
            _make_doc(
                metadata={
                    "calendar_id": "primary",
                    "calendar_name": "Primary",
                    "event_status": "confirmed",
                    "start_time_utc": "not-a-date",
                    "end_time_utc": "2026-02-20T17:30:00+00:00",
                    "event_timezone": "UTC",
                    "is_all_day": "true",
                    "attendee_emails": "single@example.com",
                }
            )
        ],
    )

    results, total = search_calendar_events(
        db_session=db_session,
        query="sync",
        start_time=None,
        end_time=None,
        organizer_email=None,
        attendee_emails=None,
        calendar_ids=None,
        event_statuses=None,
        include_all_day=None,
        creator_id=None,
        page_num=0,
        page_size=25,
        sort_by="start_time",
        sort_order="asc",
    )

    assert total == 1
    assert len(results) == 1
    event = results[0]
    assert event.start_time_utc is None
    assert event.end_time_utc is not None
    assert event.is_all_day is True
    assert event.attendee_emails == ["single@example.com"]
