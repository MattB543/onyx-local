from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.constants import DocumentSource
from onyx.db.calendar import search_calendar_events
from onyx.db.models import Connector
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CalendarSearchToolDelta
from onyx.server.query_and_chat.streaming_models import CalendarSearchToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.calendar.models import as_llm_json
from onyx.tools.tool_implementations.calendar.models import (
    compact_tool_payload_for_model,
)
from onyx.tools.tool_implementations.calendar.models import (
    is_calendar_search_schema_available,
)
from onyx.tools.tool_implementations.calendar.models import parse_datetime_maybe
from onyx.tools.tool_implementations.calendar.models import parse_string_list_maybe
from onyx.tools.tool_implementations.calendar.models import serialize_calendar_event
from onyx.utils.datetime_utils import parse_iso_datetime_in_tz
from onyx.utils.logger import setup_logger


CALENDAR_EVENT_STATUSES = {"confirmed", "tentative", "cancelled"}
SORT_BY_OPTIONS = {"start_time", "updated_at"}
SORT_ORDER_OPTIONS = {"asc", "desc"}

logger = setup_logger()


class SearchCalendarTool(Tool[None]):
    NAME = "search_calendar"
    DISPLAY_NAME = "Calendar Search"
    DESCRIPTION = (
        "Search indexed Google Calendar events by date range, people, calendar, "
        "status, or text. Use this for scheduling questions such as upcoming meetings "
        "or what meetings happen tomorrow."
    )

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        emitter: Emitter,
        user_id: str | None = None,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._session_factory = sessionmaker(bind=db_session.get_bind())
        self._creator_id: UUID | None = None
        self._invalid_user_id: str | None = None
        if user_id is not None:
            try:
                self._creator_id = UUID(user_id)
            except ValueError:
                self._invalid_user_id = user_id

    def _raise_if_invalid_user_context(self) -> None:
        if self._invalid_user_id is None:
            return
        raise ToolCallException(
            message=f"Invalid user_id context for {self.name}: {self._invalid_user_id}",
            llm_facing_message=(
                "Calendar search could not be scoped to your user identity. "
                "Please retry with a valid user context."
            ),
        )

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        if not is_calendar_search_schema_available(db_session):
            return False

        try:
            stmt = (
                select(Connector.id)
                .where(Connector.source == DocumentSource.GOOGLE_CALENDAR)
                .limit(1)
            )
            return db_session.scalar(stmt) is not None
        except SQLAlchemyError:
            logger.warning(
                "Failed checking availability for %s", cls.NAME, exc_info=True
            )
            return False

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "minProperties": 1,
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Optional text query over event titles, attendees, organizer, or location.",
                        },
                        "start_time": {
                            "type": "string",
                            "description": (
                                "Lower bound (inclusive) for event start times as ISO datetime. "
                                "Use local time without timezone suffix when timezone parameter is provided "
                                "(e.g. '2026-02-19T00:00:00'). Use UTC with Z suffix otherwise "
                                "(e.g. '2026-02-19T00:00:00Z')."
                            ),
                        },
                        "end_time": {
                            "type": "string",
                            "description": (
                                "Upper bound (inclusive) for event end times as ISO datetime. "
                                "Use local time without timezone suffix when timezone parameter is provided "
                                "(e.g. '2026-02-20T00:00:00'). Use UTC with Z suffix otherwise "
                                "(e.g. '2026-02-20T00:00:00Z')."
                            ),
                        },
                        "timezone": {
                            "type": "string",
                            "description": (
                                "IANA timezone of the user (e.g. 'America/New_York', 'Europe/London'). "
                                "When provided, start_time and end_time are interpreted as local times "
                                "in this timezone. Always include this parameter when the user's timezone is known."
                            ),
                        },
                        "organizer_email": {
                            "type": "string",
                            "description": "Filter by organizer email.",
                        },
                        "attendee_emails": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter to events containing one or more attendee emails.",
                        },
                        "calendar_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of calendar IDs to include.",
                        },
                        "event_statuses": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": sorted(list(CALENDAR_EVENT_STATUSES)),
                            },
                            "description": "Optional event statuses to include.",
                        },
                        "include_all_day": {
                            "type": "boolean",
                            "description": "If set, only return all-day events when true, or only timed events when false.",
                        },
                        "sort_by": {
                            "type": "string",
                            "enum": sorted(list(SORT_BY_OPTIONS)),
                            "description": "Primary sort field.",
                        },
                        "sort_order": {
                            "type": "string",
                            "enum": sorted(list(SORT_ORDER_OPTIONS)),
                            "description": "Sort order.",
                        },
                        "page_num": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Page number (0-indexed).",
                        },
                        "page_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "description": "Page size.",
                        },
                    },
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CalendarSearchToolStart()))

    @staticmethod
    def _parse_optional_string(value: Any, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ToolCallException(
                message=f"Invalid value for {field_name}: {value}",
                llm_facing_message=f"'{field_name}' must be a string.",
            )
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _parse_datetime_with_tz(
        value: Any,
        field_name: str,
        user_tz: ZoneInfo,
    ) -> datetime | None:
        """Parse a datetime value using timezone-aware parsing."""
        if value is None:
            return None
        if not isinstance(value, (datetime, str)):
            raise ToolCallException(
                message=f"Invalid datetime type for {field_name}: {type(value)}",
                llm_facing_message=f"'{field_name}' must be an ISO datetime string.",
            )
        if isinstance(value, str) and not value.strip():
            return None
        str_value = value.isoformat() if isinstance(value, datetime) else value
        parsed = parse_iso_datetime_in_tz(str_value, user_tz=user_tz)
        if parsed is None:
            raise ToolCallException(
                message=f"Invalid datetime format for {field_name}: {value}",
                llm_facing_message=f"'{field_name}' must be an ISO datetime string.",
            )
        return parsed

    @staticmethod
    def _has_any_filter(
        *,
        query: str | None,
        start_time: Any,
        end_time: Any,
        organizer_email: str | None,
        attendee_emails: list[str] | None,
        calendar_ids: list[str] | None,
        event_statuses: list[str] | None,
        include_all_day: bool | None,
    ) -> bool:
        return any(
            [
                bool(query),
                start_time is not None,
                end_time is not None,
                bool(organizer_email),
                bool(attendee_emails),
                bool(calendar_ids),
                bool(event_statuses),
                include_all_day is not None,
            ]
        )

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        self._raise_if_invalid_user_context()

        query = self._parse_optional_string(llm_kwargs.get("query"), "query")

        # --- timezone handling ---
        timezone_str = self._parse_optional_string(
            llm_kwargs.get("timezone"), "timezone"
        )
        user_tz: ZoneInfo | None = None
        if timezone_str:
            try:
                user_tz = ZoneInfo(timezone_str)
            except (ZoneInfoNotFoundError, KeyError):
                logger.warning(
                    "Invalid IANA timezone '%s' in %s; falling back to UTC",
                    timezone_str,
                    self.name,
                )

        # Parse start/end times with timezone awareness
        if user_tz is not None:
            start_time = self._parse_datetime_with_tz(
                llm_kwargs.get("start_time"), "start_time", user_tz
            )
            end_time = self._parse_datetime_with_tz(
                llm_kwargs.get("end_time"), "end_time", user_tz
            )
        else:
            start_time = parse_datetime_maybe(
                llm_kwargs.get("start_time"), "start_time"
            )
            end_time = parse_datetime_maybe(
                llm_kwargs.get("end_time"), "end_time"
            )
        if start_time and end_time and end_time < start_time:
            raise ToolCallException(
                message="Invalid time window for search_calendar",
                llm_facing_message="'end_time' must be greater than or equal to 'start_time'.",
            )

        organizer_email = self._parse_optional_string(
            llm_kwargs.get("organizer_email"),
            "organizer_email",
        )
        attendee_emails = parse_string_list_maybe(
            llm_kwargs.get("attendee_emails"),
            "attendee_emails",
        )
        calendar_ids = parse_string_list_maybe(
            llm_kwargs.get("calendar_ids"),
            "calendar_ids",
        )
        event_statuses = parse_string_list_maybe(
            llm_kwargs.get("event_statuses"),
            "event_statuses",
        )
        if event_statuses:
            normalized_statuses = [status.strip().lower() for status in event_statuses]
            invalid_statuses = [
                status
                for status in normalized_statuses
                if status not in CALENDAR_EVENT_STATUSES
            ]
            if invalid_statuses:
                raise ToolCallException(
                    message=f"Invalid event_statuses for {self.name}: {invalid_statuses}",
                    llm_facing_message=(
                        f"'event_statuses' must only include: {', '.join(sorted(CALENDAR_EVENT_STATUSES))}."
                    ),
                )
            event_statuses = normalized_statuses

        include_all_day_raw = llm_kwargs.get("include_all_day")
        include_all_day: bool | None = None
        if include_all_day_raw is not None:
            if not isinstance(include_all_day_raw, bool):
                raise ToolCallException(
                    message=f"Invalid include_all_day in {self.name}: {include_all_day_raw}",
                    llm_facing_message="'include_all_day' must be a boolean.",
                )
            include_all_day = include_all_day_raw

        if not self._has_any_filter(
            query=query,
            start_time=start_time,
            end_time=end_time,
            organizer_email=organizer_email,
            attendee_emails=attendee_emails,
            calendar_ids=calendar_ids,
            event_statuses=event_statuses,
            include_all_day=include_all_day,
        ):
            raise ToolCallException(
                message=f"Missing filters for {self.name}",
                llm_facing_message=(
                    "Please provide at least one filter, such as a query, time window, "
                    "organizer, attendee, calendar, status, or all-day flag."
                ),
            )

        page_num_raw = llm_kwargs.get("page_num", 0)
        page_size_raw = llm_kwargs.get("page_size", 25)
        try:
            page_num = max(0, int(page_num_raw))
            page_size = min(50, max(1, int(page_size_raw)))
        except (TypeError, ValueError):
            raise ToolCallException(
                message=f"Invalid page_num/page_size in {self.name}",
                llm_facing_message="'page_num' and 'page_size' must be integers.",
            )

        sort_by_raw = llm_kwargs.get("sort_by", "start_time")
        sort_by = sort_by_raw.strip().lower() if isinstance(sort_by_raw, str) else None
        if sort_by is None or sort_by not in SORT_BY_OPTIONS:
            raise ToolCallException(
                message=f"Invalid sort_by in {self.name}: {sort_by_raw}",
                llm_facing_message=f"'sort_by' must be one of: {', '.join(sorted(SORT_BY_OPTIONS))}.",
            )

        sort_order_raw = llm_kwargs.get("sort_order", "asc")
        sort_order = (
            sort_order_raw.strip().lower() if isinstance(sort_order_raw, str) else None
        )
        if sort_order is None or sort_order not in SORT_ORDER_OPTIONS:
            raise ToolCallException(
                message=f"Invalid sort_order in {self.name}: {sort_order_raw}",
                llm_facing_message=f"'sort_order' must be one of: {', '.join(sorted(SORT_ORDER_OPTIONS))}.",
            )

        with self._session_factory() as db_session:
            search_results, total_items = search_calendar_events(
                db_session=db_session,
                query=query,
                start_time=start_time,
                end_time=end_time,
                organizer_email=organizer_email,
                attendee_emails=attendee_emails,
                calendar_ids=calendar_ids,
                event_statuses=event_statuses,
                include_all_day=include_all_day,
                creator_id=self._creator_id,
                page_num=page_num,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
            )

        payload = {
            "status": "ok",
            "filters": {
                "query": query,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None,
                "organizer_email": organizer_email,
                "attendee_emails": attendee_emails,
                "calendar_ids": calendar_ids,
                "event_statuses": event_statuses,
                "include_all_day": include_all_day,
            },
            "sort_by": sort_by,
            "sort_order": sort_order,
            "page_num": page_num,
            "page_size": page_size,
            "total_items": total_items,
            "results": [serialize_calendar_event(event) for event in search_results],
        }

        compact_payload = compact_tool_payload_for_model(payload)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CalendarSearchToolDelta(payload=compact_payload),
            )
        )

        rich_response = json.dumps(payload, default=str)
        llm_response = as_llm_json(compact_payload, already_compacted=True)
        return ToolResponse(
            rich_response=rich_response,
            llm_facing_response=llm_response,
        )
