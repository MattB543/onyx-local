from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.utils.datetime_utils import parse_iso_datetime_to_utc
from onyx.utils.logger import setup_logger


logger = setup_logger()

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200

SortBy = Literal["start_time", "updated_at"]
SortOrder = Literal["asc", "desc"]


@dataclass(frozen=True)
class CalendarEventSearchResult:
    document_id: str
    title: str
    calendar_id: str | None
    calendar_name: str | None
    event_status: str | None
    start_time_utc: datetime | None
    end_time_utc: datetime | None
    event_timezone: str | None
    is_all_day: bool
    organizer_email: str | None
    attendee_emails: list[str]
    location: str | None
    meeting_url: str | None
    event_url: str | None
    recurring_event_id: str | None
    updated_at: datetime | None


def _normalize_page(page_num: int, page_size: int) -> tuple[int, int]:
    return max(0, page_num), min(max(1, page_size), MAX_PAGE_SIZE)


def _normalize_optional_lower(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_lower_list(values: list[str] | None) -> list[str]:
    if not values:
        return []

    normalized: list[str] = []
    for value in values:
        lowered = value.strip().lower()
        if lowered:
            normalized.append(lowered)
    return normalized


def _escape_like_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _parse_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        parsed_values: list[str] = []
        for item in value:
            if isinstance(item, str):
                trimmed = item.strip()
                if trimmed:
                    parsed_values.append(trimmed)
        return parsed_values

    if isinstance(value, str):
        trimmed = value.strip()
        return [trimmed] if trimmed else []

    return []


def _parse_metadata_datetime(
    *,
    doc_id: str,
    field_name: str,
    value: object,
) -> datetime | None:
    parsed = parse_iso_datetime_to_utc(value)
    if value is not None and parsed is None:
        logger.debug(
            "Invalid calendar metadata datetime for doc=%s field=%s value=%r",
            doc_id,
            field_name,
            value,
        )
    return parsed


def _to_result(doc: DbDocument) -> CalendarEventSearchResult:
    metadata = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
    if doc.doc_metadata is not None and not isinstance(doc.doc_metadata, dict):
        logger.debug(
            "Unexpected calendar metadata shape for doc=%s type=%s",
            doc.id,
            type(doc.doc_metadata).__name__,
        )

    calendar_id = metadata.get("calendar_id")
    calendar_name = metadata.get("calendar_name")
    event_status = metadata.get("event_status")
    event_timezone = metadata.get("event_timezone")
    organizer_email = metadata.get("organizer_email")
    location = metadata.get("location")
    meeting_url = metadata.get("meeting_url")
    event_url = metadata.get("event_url")
    recurring_event_id = metadata.get("recurring_event_id")

    return CalendarEventSearchResult(
        document_id=doc.id,
        title=doc.semantic_id,
        calendar_id=calendar_id if isinstance(calendar_id, str) else None,
        calendar_name=calendar_name if isinstance(calendar_name, str) else None,
        event_status=event_status if isinstance(event_status, str) else None,
        start_time_utc=_parse_metadata_datetime(
            doc_id=doc.id,
            field_name="start_time_utc",
            value=metadata.get("start_time_utc"),
        ),
        end_time_utc=_parse_metadata_datetime(
            doc_id=doc.id,
            field_name="end_time_utc",
            value=metadata.get("end_time_utc"),
        ),
        event_timezone=event_timezone if isinstance(event_timezone, str) else None,
        is_all_day=_parse_bool(metadata.get("is_all_day")),
        organizer_email=organizer_email if isinstance(organizer_email, str) else None,
        attendee_emails=_parse_str_list(metadata.get("attendee_emails")),
        location=location if isinstance(location, str) else None,
        meeting_url=meeting_url if isinstance(meeting_url, str) else None,
        event_url=event_url if isinstance(event_url, str) else doc.link,
        recurring_event_id=(
            recurring_event_id if isinstance(recurring_event_id, str) else None
        ),
        updated_at=doc.doc_updated_at,
    )


def _doc_metadata_field(field_name: str) -> ColumnElement:
    return DbDocument.doc_metadata[field_name].as_string()


def _doc_metadata_field_lower(field_name: str) -> ColumnElement:
    return func.lower(func.coalesce(_doc_metadata_field(field_name), ""))


def _calendar_doc_ids_stmt(creator_id: UUID | None) -> ColumnElement:
    stmt = (
        select(DocumentByConnectorCredentialPair.id)
        .join(
            Connector,
            DocumentByConnectorCredentialPair.connector_id == Connector.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .where(Connector.source == DocumentSource.GOOGLE_CALENDAR)
        .distinct()
    )

    if creator_id is not None:
        stmt = stmt.where(ConnectorCredentialPair.creator_id == creator_id)

    return stmt


def _calendar_order_by(sort_by: SortBy, sort_order: SortOrder) -> list[ColumnElement]:
    if sort_by == "start_time":
        primary_sort_expr = func.coalesce(
            _doc_metadata_field("start_time_utc"),
            _doc_metadata_field("end_time_utc"),
        )
    else:
        primary_sort_expr = DbDocument.doc_updated_at

    tie_breakers = [func.lower(DbDocument.semantic_id).asc(), DbDocument.id.asc()]
    if sort_order == "asc":
        return [primary_sort_expr.asc().nullslast(), *tie_breakers]
    return [primary_sort_expr.desc().nullsfirst(), *tie_breakers]


def search_calendar_events(
    db_session: Session,
    *,
    query: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
    organizer_email: str | None,
    attendee_emails: list[str] | None,
    calendar_ids: list[str] | None,
    event_statuses: list[str] | None,
    include_all_day: bool | None,
    creator_id: UUID | None,
    page_num: int,
    page_size: int,
    sort_by: SortBy,
    sort_order: SortOrder,
) -> tuple[list[CalendarEventSearchResult], int]:
    page_num, page_size = _normalize_page(page_num, page_size)

    normalized_query = query.strip().lower() if query and query.strip() else None
    normalized_organizer = _normalize_optional_lower(organizer_email)
    normalized_attendees = _normalize_lower_list(attendee_emails)
    normalized_calendar_ids = _normalize_lower_list(calendar_ids)
    normalized_statuses = _normalize_lower_list(event_statuses)

    calendar_doc_ids_stmt = _calendar_doc_ids_stmt(creator_id)
    docs_stmt = select(DbDocument).where(DbDocument.id.in_(calendar_doc_ids_stmt))

    event_start_expr = func.coalesce(
        _doc_metadata_field("start_time_utc"),
        _doc_metadata_field("end_time_utc"),
    )
    event_end_expr = func.coalesce(
        _doc_metadata_field("end_time_utc"),
        _doc_metadata_field("start_time_utc"),
    )

    if start_time is not None:
        docs_stmt = docs_stmt.where(event_end_expr >= start_time.isoformat())
    if end_time is not None:
        docs_stmt = docs_stmt.where(event_start_expr <= end_time.isoformat())

    if normalized_organizer:
        docs_stmt = docs_stmt.where(
            _doc_metadata_field_lower("organizer_email") == normalized_organizer
        )

    if normalized_attendees:
        attendee_match_conditions = [
            _doc_metadata_field_lower("attendee_emails").like(
                f"%{_escape_like_query(email)}%",
                escape="\\",
            )
            for email in normalized_attendees
        ]
        docs_stmt = docs_stmt.where(or_(*attendee_match_conditions))

    if normalized_calendar_ids:
        docs_stmt = docs_stmt.where(
            _doc_metadata_field_lower("calendar_id").in_(normalized_calendar_ids)
        )

    if normalized_statuses:
        docs_stmt = docs_stmt.where(
            _doc_metadata_field_lower("event_status").in_(normalized_statuses)
        )

    if include_all_day is not None:
        target_value = "true" if include_all_day else "false"
        docs_stmt = docs_stmt.where(
            _doc_metadata_field_lower("is_all_day") == target_value
        )

    if normalized_query:
        like_q = f"%{_escape_like_query(normalized_query)}%"
        docs_stmt = docs_stmt.where(
            or_(
                func.lower(DbDocument.semantic_id).like(like_q, escape="\\"),
                _doc_metadata_field_lower("calendar_name").like(like_q, escape="\\"),
                _doc_metadata_field_lower("calendar_id").like(like_q, escape="\\"),
                _doc_metadata_field_lower("organizer_email").like(like_q, escape="\\"),
                _doc_metadata_field_lower("location").like(like_q, escape="\\"),
                _doc_metadata_field_lower("event_status").like(like_q, escape="\\"),
                _doc_metadata_field_lower("attendee_emails").like(like_q, escape="\\"),
            )
        )

    total_items = int(
        db_session.scalar(select(func.count()).select_from(docs_stmt.subquery())) or 0
    )
    paged_stmt = (
        docs_stmt.order_by(*_calendar_order_by(sort_by, sort_order))
        .offset(page_num * page_size)
        .limit(page_size)
    )
    docs = list(db_session.scalars(paged_stmt).all())

    logger.debug(
        "Calendar search returned %s rows (total=%s, page_num=%s, page_size=%s)",
        len(docs),
        total_items,
        page_num,
        page_size,
    )

    return [_to_result(doc) for doc in docs], total_items
