from __future__ import annotations

from datetime import datetime
from datetime import timezone
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError


def parse_iso_datetime_to_utc(value: object) -> datetime | None:
    """Parse an ISO datetime value and normalize to UTC.

    Returns None for empty/invalid values.
    """

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_iso_datetime_in_tz(
    value: str | None,
    user_tz: ZoneInfo | None = None,
) -> datetime | None:
    """Parse an ISO datetime string. If the string has no timezone info
    and user_tz is provided, interpret it in the user's timezone and
    convert to UTC. Otherwise fall back to treating it as UTC."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None

    # Normalise the "Z" shorthand to a proper UTC offset so that
    # ``datetime.fromisoformat`` can handle it on all Python versions.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        # Try date-only (e.g., "2026-02-19")
        try:
            from datetime import date as date_type
            from datetime import time as time_type

            d = date_type.fromisoformat(value)
            parsed = datetime.combine(d, time_type.min)
        except ValueError:
            return None

    if parsed.tzinfo is not None:
        # Already has timezone info -- convert directly to UTC
        return parsed.astimezone(timezone.utc)

    if user_tz is not None:
        # Naive datetime -- interpret in user's timezone, then convert to UTC
        return parsed.replace(tzinfo=user_tz).astimezone(timezone.utc)

    # No timezone context -- treat as UTC
    return parsed.replace(tzinfo=timezone.utc)
