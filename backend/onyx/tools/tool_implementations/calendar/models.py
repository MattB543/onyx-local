from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from onyx.db.calendar import CalendarEventSearchResult
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.payload_utils import as_llm_json
from onyx.tools.tool_implementations.payload_utils import compact_tool_payload_for_model
from onyx.utils.datetime_utils import parse_iso_datetime_to_utc

REQUIRED_CALENDAR_TABLES = {
    "connector",
    "connector_credential_pair",
    "document",
    "document_by_connector_credential_pair",
}


def is_calendar_search_schema_available(db_session: Session) -> bool:
    inspector = inspect(db_session.get_bind())
    existing_tables = set(inspector.get_table_names())
    return REQUIRED_CALENDAR_TABLES.issubset(existing_tables)


def is_calendar_schema_available(db_session: Session) -> bool:
    # Backwards-compatible alias.
    return is_calendar_search_schema_available(db_session)


def parse_datetime_maybe(value: Any, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, (datetime, str)):
        raise ToolCallException(
            message=f"Invalid datetime type for {field_name}: {type(value)}",
            llm_facing_message=f"'{field_name}' must be an ISO datetime string.",
        )
    if isinstance(value, str) and not value.strip():
        return None
    parsed = parse_iso_datetime_to_utc(value)
    if parsed is None:
        raise ToolCallException(
            message=f"Invalid datetime format for {field_name}: {value}",
            llm_facing_message=f"'{field_name}' must be an ISO datetime string.",
        )
    return parsed


def parse_string_list_maybe(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return [trimmed] if trimmed else []
    if not isinstance(value, list):
        raise ToolCallException(
            message=f"Invalid list value for {field_name}: {value}",
            llm_facing_message=f"'{field_name}' must be a list of strings.",
        )

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if trimmed:
            normalized.append(trimmed)

    return normalized


def serialize_calendar_event(event: CalendarEventSearchResult) -> dict[str, Any]:
    # Compute localized start/end times when the event carries a timezone.
    start_local: str | None = None
    end_local: str | None = None
    if event.event_timezone and event.start_time_utc:
        try:
            evt_tz = ZoneInfo(event.event_timezone)
            start_local = event.start_time_utc.astimezone(evt_tz).isoformat()
        except Exception:
            pass
    if event.event_timezone and event.end_time_utc:
        try:
            evt_tz = ZoneInfo(event.event_timezone)
            end_local = event.end_time_utc.astimezone(evt_tz).isoformat()
        except Exception:
            pass

    return {
        "document_id": event.document_id,
        "title": event.title,
        "calendar_id": event.calendar_id,
        "calendar_name": event.calendar_name,
        "event_status": event.event_status,
        "start_time_utc": (
            event.start_time_utc.isoformat() if event.start_time_utc else None
        ),
        "end_time_utc": event.end_time_utc.isoformat() if event.end_time_utc else None,
        "start_time_local": start_local,
        "end_time_local": end_local,
        "event_timezone": event.event_timezone,
        "is_all_day": event.is_all_day,
        "organizer_email": event.organizer_email,
        "attendee_emails": event.attendee_emails,
        "location": event.location,
        "meeting_url": event.meeting_url,
        "event_url": event.event_url,
        "recurring_event_id": event.recurring_event_id,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }
