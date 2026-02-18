from datetime import datetime
from datetime import timezone
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_calendar.connector import GoogleCalendarConnector
from onyx.connectors.google_calendar.models import GoogleCalendarCheckpoint
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)


def test_event_to_document() -> None:
    connector = GoogleCalendarConnector(
        include_event_descriptions=True,
        include_attendees=True,
    )
    connector._calendar_names = {"primary": "Primary Calendar"}

    event = {
        "id": "abc123",
        "status": "confirmed",
        "summary": "Product Sync",
        "description": "<p>Review launch blockers</p>",
        "updated": "2026-02-17T10:30:00Z",
        "start": {"dateTime": "2026-02-18T16:00:00Z", "timeZone": "UTC"},
        "end": {"dateTime": "2026-02-18T16:30:00Z", "timeZone": "UTC"},
        "organizer": {"email": "pm@example.com"},
        "attendees": [
            {"email": "pm@example.com", "responseStatus": "accepted", "self": True},
            {"email": "eng@example.com", "responseStatus": "tentative"},
        ],
        "location": "Room A",
        "hangoutLink": "https://meet.google.com/abc-defg-hij",
        "htmlLink": "https://calendar.google.com/event?eid=abc123",
    }

    doc = connector._event_to_document(event, "primary")
    assert doc is not None
    assert doc.id == "google_calendar:primary:abc123"
    assert doc.source == DocumentSource.GOOGLE_CALENDAR
    assert doc.semantic_identifier == "Product Sync"
    assert doc.metadata["calendar_name"] == "Primary Calendar"
    assert doc.metadata["event_status"] == "confirmed"
    assert doc.metadata["organizer_email"] == "pm@example.com"
    assert doc.metadata["meeting_url"] == "https://meet.google.com/abc-defg-hij"
    assert doc.doc_updated_at == datetime(2026, 2, 17, 10, 30, tzinfo=timezone.utc)
    assert len(doc.sections) == 1
    assert isinstance(doc.sections[0], TextSection)
    assert "Review launch blockers" in doc.sections[0].text


def test_should_skip_declined_or_cancelled_events() -> None:
    connector = GoogleCalendarConnector(include_declined_events=False)

    declined_event = {
        "id": "declined",
        "status": "confirmed",
        "attendees": [{"self": True, "responseStatus": "declined"}],
    }
    cancelled_event = {"id": "cancelled", "status": "cancelled"}
    confirmed_event = {"id": "confirmed", "status": "confirmed"}

    assert connector._should_skip_event(declined_event)
    assert connector._should_skip_event(cancelled_event)
    assert not connector._should_skip_event(confirmed_event)


def test_checkpoint_progression() -> None:
    connector = GoogleCalendarConnector()

    pages: dict[tuple[str, str | None], tuple[list[dict], str | None]] = {
        ("team", None): ([{"id": "t1"}, {"id": "t2"}], "token-team-page-2"),
        ("team", "token-team-page-2"): ([{"id": "t3"}], None),
        ("primary", None): ([{"id": "p1"}], None),
    }

    def fake_fetch(
        calendar_id: str,
        start: float,  # noqa: ARG001
        page_token: str | None,
    ) -> tuple[list[dict], str | None]:
        return pages[(calendar_id, page_token)]

    def fake_event_to_document(event: dict, calendar_id: str) -> Document:
        event_id = event["id"]
        return Document(
            id=f"google_calendar:{calendar_id}:{event_id}",
            semantic_identifier=f"{calendar_id}:{event_id}",
            sections=[TextSection(text=f"{calendar_id}:{event_id}")],
            source=DocumentSource.GOOGLE_CALENDAR,
            metadata={},
        )

    checkpoint = connector.build_dummy_checkpoint()
    assert isinstance(checkpoint, GoogleCalendarCheckpoint)

    with patch.object(
        connector, "_resolve_calendar_ids", return_value=["team", "primary"]
    ):
        with patch.object(
            connector,
            "_fetch_calendar_events_page",
            side_effect=fake_fetch,
        ):
            with patch.object(
                connector,
                "_event_to_document",
                side_effect=fake_event_to_document,
            ):
                outputs = load_everything_from_checkpoint_connector_from_checkpoint(
                    connector=connector,
                    start=0,
                    end=1_000,
                    checkpoint=checkpoint,
                )

    document_ids = [
        item.id
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert document_ids == [
        "google_calendar:team:t1",
        "google_calendar:team:t2",
        "google_calendar:team:t3",
        "google_calendar:primary:p1",
    ]

    final_checkpoint = outputs[-1].next_checkpoint
    assert final_checkpoint.has_more is False
    assert final_checkpoint.calendar_cursor == 2
