from pydantic import Field

from onyx.connectors.interfaces import ConnectorCheckpoint


class GoogleCalendarCheckpoint(ConnectorCheckpoint):
    # resolved list of calendars for this indexing attempt
    calendar_ids: list[str] | None = None
    # index of the current calendar in calendar_ids
    calendar_cursor: int = 0
    # pagination token per calendar id
    page_tokens: dict[str, str | None] = Field(default_factory=dict)
