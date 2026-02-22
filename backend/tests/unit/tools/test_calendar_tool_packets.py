"""Tests for Calendar tool streaming packet emissions and session replay helpers."""

from datetime import datetime
from datetime import timezone
from queue import Queue
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from onyx.chat.emitter import Emitter
from onyx.db.calendar import CalendarEventSearchResult
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.session_loading import (
    create_calendar_search_packets,
)
from onyx.server.query_and_chat.streaming_models import CalendarSearchToolDelta
from onyx.server.query_and_chat.streaming_models import CalendarSearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.calendar.search_calendar_tool import (
    SearchCalendarTool,
)


def _make_sqlite_session():
    engine = create_engine("sqlite://")
    return sessionmaker(bind=engine)()


def test_calendar_search_emit_start() -> None:
    bus: Queue = Queue()
    emitter = Emitter(bus)
    db_session = _make_sqlite_session()
    try:
        tool = SearchCalendarTool(tool_id=1, db_session=db_session, emitter=emitter)
        placement = Placement(turn_index=0, tab_index=0)

        tool.emit_start(placement)

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CalendarSearchToolStart)
        assert packet.placement == placement
    finally:
        db_session.close()


def test_calendar_search_is_unavailable_when_tables_missing() -> None:
    db_session = _make_sqlite_session()
    try:
        assert SearchCalendarTool.is_available(db_session) is False
    finally:
        db_session.close()


def test_calendar_search_run_emits_delta() -> None:
    bus: Queue = Queue()
    emitter = Emitter(bus)
    db_session = _make_sqlite_session()
    try:
        tool = SearchCalendarTool(tool_id=1, db_session=db_session, emitter=emitter)
        placement = Placement(turn_index=0, tab_index=0)

        event = CalendarEventSearchResult(
            document_id="google_calendar:primary:abc123",
            title="Team Sync",
            calendar_id="primary",
            calendar_name="Primary",
            event_status="confirmed",
            start_time_utc=datetime(2026, 2, 20, 17, 0, tzinfo=timezone.utc),
            end_time_utc=datetime(2026, 2, 20, 17, 30, tzinfo=timezone.utc),
            event_timezone="UTC",
            is_all_day=False,
            organizer_email="owner@example.com",
            attendee_emails=["owner@example.com", "teammate@example.com"],
            location="Zoom",
            meeting_url="https://meet.google.com/abc-defg-hij",
            event_url="https://calendar.google.com/event?eid=abc123",
            recurring_event_id=None,
            updated_at=datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc),
        )

        with patch(
            "onyx.tools.tool_implementations.calendar.search_calendar_tool.search_calendar_events"
        ) as mock_search:
            mock_search.return_value = ([event], 1)

            result = tool.run(
                placement=placement,
                query="team sync",
                page_num=0,
                page_size=10,
            )

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CalendarSearchToolDelta)
        assert packet.obj.payload["status"] == "ok"
        assert packet.obj.payload["total_items"] == 1
        assert '"status": "ok"' in result.llm_facing_response
    finally:
        db_session.close()


def test_calendar_search_requires_at_least_one_filter() -> None:
    bus: Queue = Queue()
    emitter = Emitter(bus)
    db_session = _make_sqlite_session()
    try:
        tool = SearchCalendarTool(tool_id=1, db_session=db_session, emitter=emitter)

        with pytest.raises(ToolCallException, match="Missing filters"):
            tool.run(placement=Placement(turn_index=0, tab_index=0))
    finally:
        db_session.close()


def test_calendar_search_rejects_invalid_user_context() -> None:
    bus: Queue = Queue()
    emitter = Emitter(bus)
    db_session = _make_sqlite_session()
    try:
        tool = SearchCalendarTool(
            tool_id=1,
            db_session=db_session,
            emitter=emitter,
            user_id="not-a-uuid",
        )

        with pytest.raises(ToolCallException, match="Invalid user_id context"):
            tool.run(
                placement=Placement(turn_index=0, tab_index=0),
                query="team sync",
            )
    finally:
        db_session.close()


def test_create_calendar_search_packets() -> None:
    packets = create_calendar_search_packets(
        tool_call_response='{"status":"ok","results":[{"title":"Team Sync"}]}',
        turn_index=1,
        tab_index=0,
    )

    assert len(packets) == 3
    assert isinstance(packets[0].obj, CalendarSearchToolStart)
    assert isinstance(packets[1].obj, CalendarSearchToolDelta)
    assert isinstance(packets[2].obj, SectionEnd)
    assert packets[1].obj.payload["status"] == "ok"
