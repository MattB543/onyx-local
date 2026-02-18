import copy
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone
from typing import Any
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError  # type: ignore
from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.google_calendar.models import GoogleCalendarCheckpoint
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.google_utils.google_utils import (
    execute_paginated_retrieval_with_max_pages,
)
from onyx.connectors.google_utils.google_utils import PAGE_TOKEN_KEY
from onyx.connectors.google_utils.resources import get_calendar_service
from onyx.connectors.google_utils.resources import GoogleCalendarService
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from onyx.connectors.google_utils.shared_constants import ONYX_SCOPE_INSTRUCTIONS
from onyx.connectors.google_utils.shared_constants import SLIM_BATCH_SIZE
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_LOOKAHEAD_DAYS = 365
EVENT_PAGE_SIZE = 250
PAGES_PER_CHECKPOINT = 1

CALENDAR_LIST_FIELDS = "nextPageToken,items(id,summary)"
EVENT_LIST_FIELDS = (
    "nextPageToken,items("
    "id,status,summary,description,updated,"
    "start,end,"
    "organizer(email,displayName),"
    "attendees(email,displayName,responseStatus,self),"
    "htmlLink,location,hangoutLink,"
    "conferenceData(entryPoints(uri,entryPointType)),"
    "recurringEventId"
    ")"
)


def _csv_to_str_list(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [value.strip() for value in raw_value.split(",") if value.strip()]


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _to_rfc3339(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_rfc3339(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_timezone(timezone_name: str | None) -> ZoneInfo:
    if timezone_name:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning(
                "Unknown timezone '%s' from Google Calendar event. Falling back to UTC.",
                timezone_name,
            )
    return ZoneInfo("UTC")


def _parse_event_time(
    event_time: dict[str, Any] | None,
    fallback_timezone: str | None,
) -> tuple[datetime | None, bool, str]:
    if not isinstance(event_time, dict):
        timezone_name = fallback_timezone or "UTC"
        return None, False, timezone_name

    timezone_name = event_time.get("timeZone") or fallback_timezone or "UTC"

    date_time_value = event_time.get("dateTime")
    if isinstance(date_time_value, str):
        parsed_datetime = _parse_rfc3339(date_time_value)
        if parsed_datetime:
            return parsed_datetime.astimezone(timezone.utc), False, timezone_name

    date_value = event_time.get("date")
    if isinstance(date_value, str):
        try:
            parsed_date = date.fromisoformat(date_value)
        except ValueError:
            return None, True, timezone_name

        parsed_datetime = datetime.combine(
            parsed_date, time.min, tzinfo=_safe_timezone(timezone_name)
        ).astimezone(timezone.utc)
        return parsed_datetime, True, timezone_name

    return None, False, timezone_name


def _extract_meeting_link(event: dict[str, Any]) -> str | None:
    hangout_link = event.get("hangoutLink")
    if isinstance(hangout_link, str) and hangout_link:
        return hangout_link

    conference_data = event.get("conferenceData")
    if not isinstance(conference_data, dict):
        return None

    entry_points = conference_data.get("entryPoints")
    if not isinstance(entry_points, list):
        return None

    for entry_point in entry_points:
        if not isinstance(entry_point, dict):
            continue
        uri = entry_point.get("uri")
        if isinstance(uri, str) and uri:
            return uri

    return None


def _format_attendee(attendee: dict[str, Any]) -> str:
    attendee_email = attendee.get("email")
    attendee_name = attendee.get("displayName")
    response_status = attendee.get("responseStatus")

    participant_name = None
    if isinstance(attendee_name, str) and attendee_name.strip():
        participant_name = attendee_name.strip()
    elif isinstance(attendee_email, str) and attendee_email.strip():
        participant_name = attendee_email.strip()
    else:
        participant_name = "Unknown attendee"

    if isinstance(response_status, str) and response_status.strip():
        return f"{participant_name} ({response_status.strip()})"

    return participant_name


class GoogleCalendarConnector(
    CheckpointedConnector[GoogleCalendarCheckpoint],
    SlimConnector,
):
    def __init__(
        self,
        calendar_ids: str | None = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
        include_declined_events: bool = True,
        include_event_descriptions: bool = True,
        include_attendees: bool = True,
    ) -> None:
        if lookback_days < 0:
            raise ConnectorValidationError("lookback_days must be >= 0")
        if lookahead_days < 0:
            raise ConnectorValidationError("lookahead_days must be >= 0")

        self._configured_calendar_ids = _deduplicate(_csv_to_str_list(calendar_ids))
        self.lookback_days = lookback_days
        self.lookahead_days = lookahead_days
        self.include_declined_events = include_declined_events
        self.include_event_descriptions = include_event_descriptions
        self.include_attendees = include_attendees

        self._creds: OAuthCredentials | ServiceAccountCredentials | None = None
        self._calendar_service: GoogleCalendarService | None = None
        self._primary_admin_email: str | None = None
        self._calendar_names: dict[str, str] = {}

    @property
    def primary_admin_email(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, should not call this property "
                "before calling load_credentials"
            )
        return self._primary_admin_email

    @property
    def creds(self) -> OAuthCredentials | ServiceAccountCredentials:
        if self._creds is None:
            raise RuntimeError(
                "Creds missing, should not call this property "
                "before calling load_credentials"
            )
        return self._creds

    @property
    def calendar_service(self) -> GoogleCalendarService:
        if self._calendar_service is None:
            raise ConnectorMissingCredentialError("Google Calendar")
        return self._calendar_service

    def _build_calendar_service(self) -> GoogleCalendarService:
        if isinstance(self.creds, ServiceAccountCredentials):
            return get_calendar_service(self.creds, self.primary_admin_email)
        return get_calendar_service(self.creds)

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        try:
            self._primary_admin_email = credentials[DB_CREDENTIALS_PRIMARY_ADMIN_KEY]
        except KeyError as e:
            raise ValueError("Credentials json missing primary admin key") from e

        self._creds, new_creds_dict = get_google_creds(
            credentials=credentials,
            source=DocumentSource.GOOGLE_CALENDAR,
        )
        self._calendar_service = self._build_calendar_service()
        return new_creds_dict

    def _ensure_calendar_names(self, calendar_ids: list[str]) -> None:
        for calendar_id in calendar_ids:
            if calendar_id in self._calendar_names:
                continue

            try:
                calendar = (
                    self.calendar_service.calendarList()
                    .get(calendarId=calendar_id, fields="id,summary")
                    .execute()
                )
                summary = calendar.get("summary")
                if isinstance(summary, str) and summary.strip():
                    self._calendar_names[calendar_id] = summary.strip()
                else:
                    self._calendar_names[calendar_id] = calendar_id
            except Exception:
                self._calendar_names[calendar_id] = calendar_id

    def _resolve_calendar_ids(self) -> list[str]:
        if self._configured_calendar_ids:
            self._ensure_calendar_names(self._configured_calendar_ids)
            return list(self._configured_calendar_ids)

        calendar_ids: list[str] = []
        for calendar in execute_paginated_retrieval(
            retrieval_function=self.calendar_service.calendarList().list,
            list_key="items",
            maxResults=EVENT_PAGE_SIZE,
            fields=CALENDAR_LIST_FIELDS,
        ):
            calendar_id = calendar.get("id")
            if not isinstance(calendar_id, str) or not calendar_id:
                continue

            calendar_ids.append(calendar_id)
            summary = calendar.get("summary")
            if isinstance(summary, str) and summary.strip():
                self._calendar_names[calendar_id] = summary.strip()
            else:
                self._calendar_names[calendar_id] = calendar_id

        deduplicated_calendar_ids = _deduplicate(calendar_ids)
        if not deduplicated_calendar_ids:
            raise ConnectorValidationError(
                "No accessible Google Calendar calendars were found."
            )

        self._ensure_calendar_names(deduplicated_calendar_ids)
        return deduplicated_calendar_ids

    def _build_events_request_kwargs(
        self,
        start: SecondsSinceUnixEpoch,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(tz=timezone.utc)
        horizon_start = now - timedelta(days=self.lookback_days)
        horizon_end = now + timedelta(days=self.lookahead_days)

        kwargs: dict[str, Any] = {
            "fields": EVENT_LIST_FIELDS,
            "maxResults": EVENT_PAGE_SIZE,
            "showDeleted": True,
            "singleEvents": True,
            "timeMax": _to_rfc3339(horizon_end),
            "timeMin": _to_rfc3339(horizon_start),
            "timeZone": "UTC",
        }

        if start > 0:
            window_start = datetime.fromtimestamp(start, tz=timezone.utc)
            kwargs["updatedMin"] = _to_rfc3339(window_start)

        if page_token:
            kwargs[PAGE_TOKEN_KEY] = page_token

        return kwargs

    def _fetch_calendar_events_page(
        self,
        calendar_id: str,
        start: SecondsSinceUnixEpoch,
        page_token: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        events: list[dict[str, Any]] = []
        next_page_token: str | None = None

        request_kwargs = self._build_events_request_kwargs(
            start=start,
            page_token=page_token,
        )

        for event_or_next_page_token in execute_paginated_retrieval_with_max_pages(
            max_num_pages=PAGES_PER_CHECKPOINT,
            retrieval_function=self.calendar_service.events().list,
            list_key="items",
            calendarId=calendar_id,
            **request_kwargs,
        ):
            if isinstance(event_or_next_page_token, str):
                next_page_token = event_or_next_page_token
            else:
                events.append(event_or_next_page_token)

        return events, next_page_token

    def _should_skip_event(self, event: dict[str, Any]) -> bool:
        if event.get("status") == "cancelled":
            return True

        if self.include_declined_events:
            return False

        attendees = event.get("attendees")
        if not isinstance(attendees, list):
            return False

        for attendee in attendees:
            if not isinstance(attendee, dict):
                continue
            if attendee.get("self") and attendee.get("responseStatus") == "declined":
                return True

        return False

    def _event_to_document(
        self,
        event: dict[str, Any],
        calendar_id: str,
    ) -> Document | None:
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id:
            return None

        start_time, is_all_day, start_timezone = _parse_event_time(
            event.get("start"), None
        )
        end_time, _, end_timezone = _parse_event_time(
            event.get("end"), start_timezone
        )
        event_timezone = end_timezone or start_timezone or "UTC"

        calendar_name = self._calendar_names.get(calendar_id, calendar_id)
        event_status = str(event.get("status", "confirmed"))
        semantic_identifier = str(event.get("summary") or "").strip() or "(No title)"

        organizer_email: str | None = None
        organizer = event.get("organizer")
        if isinstance(organizer, dict):
            raw_organizer_email = organizer.get("email")
            if isinstance(raw_organizer_email, str) and raw_organizer_email.strip():
                organizer_email = raw_organizer_email.strip()

        attendee_emails: list[str] = []
        attendee_lines: list[str] = []
        attendees = event.get("attendees")
        if isinstance(attendees, list):
            for attendee in attendees:
                if not isinstance(attendee, dict):
                    continue
                attendee_email = attendee.get("email")
                if isinstance(attendee_email, str) and attendee_email.strip():
                    attendee_emails.append(attendee_email.strip())
                attendee_lines.append(_format_attendee(attendee))

        meeting_link = _extract_meeting_link(event)
        event_link = event.get("htmlLink")
        event_location = event.get("location")

        description_text = ""
        raw_description = event.get("description")
        if self.include_event_descriptions and isinstance(raw_description, str):
            cleaned_description = parse_html_page_basic(raw_description).strip()
            description_text = cleaned_description or raw_description.strip()

        section_lines = [
            f"Title: {semantic_identifier}",
            f"Calendar: {calendar_name}",
            f"Status: {event_status}",
            f"All Day: {'Yes' if is_all_day else 'No'}",
            f"Event Timezone: {event_timezone}",
        ]
        if start_time:
            section_lines.append(f"Start (UTC): {start_time.isoformat()}")
        if end_time:
            section_lines.append(f"End (UTC): {end_time.isoformat()}")
        if organizer_email:
            section_lines.append(f"Organizer: {organizer_email}")
        if self.include_attendees and attendee_lines:
            section_lines.append("Attendees:\n" + "\n".join(attendee_lines))
        if isinstance(event_location, str) and event_location.strip():
            section_lines.append(f"Location: {event_location.strip()}")
        if meeting_link:
            section_lines.append(f"Meeting Link: {meeting_link}")
        if description_text:
            section_lines.append(f"Description:\n{description_text}")

        metadata: dict[str, str | list[str]] = {
            "calendar_id": calendar_id,
            "calendar_name": calendar_name,
            "event_status": event_status,
            "event_timezone": event_timezone,
            "is_all_day": "true" if is_all_day else "false",
        }
        if start_time:
            metadata["start_time_utc"] = start_time.isoformat()
        if end_time:
            metadata["end_time_utc"] = end_time.isoformat()
        if organizer_email:
            metadata["organizer_email"] = organizer_email
        if self.include_attendees and attendee_emails:
            metadata["attendee_emails"] = attendee_emails
        recurring_event_id = event.get("recurringEventId")
        if isinstance(recurring_event_id, str) and recurring_event_id.strip():
            metadata["recurring_event_id"] = recurring_event_id.strip()
        if isinstance(event_location, str) and event_location.strip():
            metadata["location"] = event_location.strip()
        if meeting_link:
            metadata["meeting_url"] = meeting_link
        if isinstance(event_link, str) and event_link.strip():
            metadata["event_url"] = event_link.strip()

        document_id = f"google_calendar:{calendar_id}:{event_id}"
        return Document(
            id=document_id,
            sections=[
                TextSection(
                    link=event_link if isinstance(event_link, str) else None,
                    text="\n".join(section_lines),
                )
            ],
            source=DocumentSource.GOOGLE_CALENDAR,
            semantic_identifier=semantic_identifier,
            metadata=metadata,
            doc_updated_at=_parse_rfc3339(
                event.get("updated") if isinstance(event.get("updated"), str) else None
            ),
        )

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        checkpoint: GoogleCalendarCheckpoint,
    ) -> CheckpointOutput[GoogleCalendarCheckpoint]:
        checkpoint = copy.deepcopy(checkpoint)

        if checkpoint.calendar_ids is None:
            checkpoint.calendar_ids = self._resolve_calendar_ids()

        if not checkpoint.calendar_ids:
            checkpoint.has_more = False
            return checkpoint

        if checkpoint.calendar_cursor >= len(checkpoint.calendar_ids):
            checkpoint.has_more = False
            return checkpoint

        calendar_id = checkpoint.calendar_ids[checkpoint.calendar_cursor]
        page_token = checkpoint.page_tokens.get(calendar_id)
        events, next_page_token = self._fetch_calendar_events_page(
            calendar_id=calendar_id,
            start=start,
            page_token=page_token,
        )

        for event in events:
            if self._should_skip_event(event):
                continue

            try:
                document = self._event_to_document(event, calendar_id)
                if document is not None:
                    yield document
            except Exception as e:
                raw_event_id = event.get("id")
                event_id = (
                    raw_event_id
                    if isinstance(raw_event_id, str) and raw_event_id
                    else "unknown"
                )
                event_link = event.get("htmlLink")
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=f"google_calendar:{calendar_id}:{event_id}",
                        document_link=(
                            event_link if isinstance(event_link, str) else None
                        ),
                    ),
                    failure_message=f"Failed to process Google Calendar event '{event_id}'",
                    exception=e,
                )

        if next_page_token:
            checkpoint.page_tokens[calendar_id] = next_page_token
            return checkpoint

        checkpoint.page_tokens.pop(calendar_id, None)
        checkpoint.calendar_cursor += 1
        if checkpoint.calendar_cursor >= len(checkpoint.calendar_ids):
            checkpoint.has_more = False

        return checkpoint

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: GoogleCalendarCheckpoint,
    ) -> CheckpointOutput[GoogleCalendarCheckpoint]:
        try:
            return self._load_from_checkpoint(
                start=start,
                checkpoint=checkpoint,
            )
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        try:
            slim_docs_batch: list[SlimDocument | HierarchyNode] = []

            calendar_ids = self._resolve_calendar_ids()
            for calendar_id in calendar_ids:
                page_token: str | None = None

                while True:
                    # Slim retrieval is used for reconciliation / pruning and should
                    # represent the current full in-scope horizon rather than a
                    # checkpoint window.
                    query_start = 0
                    events, next_page_token = self._fetch_calendar_events_page(
                        calendar_id=calendar_id,
                        start=query_start,
                        page_token=page_token,
                    )
                    for event in events:
                        if self._should_skip_event(event):
                            continue

                        event_id = event.get("id")
                        if not isinstance(event_id, str) or not event_id:
                            continue

                        slim_docs_batch.append(
                            SlimDocument(
                                id=f"google_calendar:{calendar_id}:{event_id}",
                            )
                        )

                        if len(slim_docs_batch) >= SLIM_BATCH_SIZE:
                            yield slim_docs_batch
                            slim_docs_batch = []

                            if callback:
                                if callback.should_stop():
                                    return
                                callback.progress(
                                    "google_calendar_retrieve_all_slim_docs", 1
                                )

                    if not next_page_token:
                        break
                    page_token = next_page_token

            if slim_docs_batch:
                yield slim_docs_batch

        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    @override
    def build_dummy_checkpoint(self) -> GoogleCalendarCheckpoint:
        return GoogleCalendarCheckpoint(has_more=True)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> GoogleCalendarCheckpoint:
        return GoogleCalendarCheckpoint.model_validate_json(checkpoint_json)

    def validate_connector_settings(self) -> None:
        if self._creds is None or self._calendar_service is None:
            raise ConnectorMissingCredentialError("Google Calendar")

        try:
            self.calendar_service.calendarList().list(
                maxResults=1, fields="items(id)"
            ).execute()

            # Fail fast for explicit calendar targets so misconfigured IDs
            # don't only surface later during background sync.
            for calendar_id in self._configured_calendar_ids:
                self.calendar_service.events().list(
                    calendarId=calendar_id,
                    maxResults=1,
                    fields="items(id)",
                    singleEvents=False,
                ).execute()
        except HttpError as e:
            status_code = e.resp.status if e.resp else None
            if status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Google Calendar credentials (401)."
                )
            if status_code == 404 and self._configured_calendar_ids:
                raise ConnectorValidationError(
                    "One or more configured calendar_ids are not accessible. "
                    "Please verify each calendar ID and access permissions."
                )
            if status_code == 403:
                raise InsufficientPermissionsError(
                    "Google Calendar app lacks required permissions (403). "
                    "Please ensure required scopes are granted and Calendar API is enabled."
                )
            raise ConnectorValidationError(
                f"Unexpected Google Calendar error (status={status_code}): {e}"
            )
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise InsufficientPermissionsError(
                    "Google Calendar credentials are missing required scopes. "
                    f"{ONYX_SCOPE_INSTRUCTIONS}"
                )
            raise ConnectorValidationError(
                f"Unexpected error during Google Calendar validation: {e}"
            )
