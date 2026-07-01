from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

# Matches a bare calendar date with no time component (e.g. "2026-01-31").
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_date_only(value: str) -> bool:
    """True if ``value`` is a bare ``YYYY-MM-DD`` date with no time component."""
    return bool(_DATE_ONLY_RE.match(value.strip()))


# ---------------------------------------------------------------------------
# CSV column headers
# ---------------------------------------------------------------------------

ORGANIZATION_CSV_HEADERS = [
    "id",
    "name",
    "website",
    "type",
    "sector",
    "location",
    "size",
    "notes",
    "tags",
    "created_by",
    "created_at",
    "updated_at",
]

CONTACT_CSV_HEADERS = [
    "id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "title",
    "organization_name",
    "owner_emails",
    "source",
    "status",
    "category",
    "party_affiliation",
    "us_state",
    "principal",
    "notes",
    "linkedin_url",
    "location",
    "profile_picture_url",
    "tags",
    "created_by",
    "created_at",
    "updated_at",
]

INTERACTION_CSV_HEADERS = [
    "id",
    "type",
    "title",
    "summary",
    "contact_email",
    "organization_name",
    "organizer_users",
    "organizer_contacts",
    "attendee_users",
    "attendee_contacts",
    "occurred_at",
    "logged_by",
    "created_at",
    "updated_at",
]

# Import headers — only mutable fields (subset of export headers)
ORGANIZATION_IMPORT_HEADERS = [
    "name",
    "website",
    "type",
    "sector",
    "location",
    "size",
    "notes",
    "tags",
]

CONTACT_IMPORT_HEADERS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "title",
    "organization_name",
    "owner_emails",
    "source",
    "status",
    "category",
    "party_affiliation",
    "us_state",
    "principal",
    "notes",
    "linkedin_url",
    "location",
    "tags",
]

# New CRM policy fields are optional on import so older exports (which lack these
# columns) still validate. Absent column => field simply not set.
CONTACT_OPTIONAL_IMPORT_HEADERS = [
    "party_affiliation",
    "us_state",
    "principal",
]

INTERACTION_IMPORT_HEADERS = [
    "type",
    "title",
    "summary",
    "contact_email",
    "organization_name",
    "organizer_users",
    "organizer_contacts",
    "attendee_users",
    "attendee_contacts",
    "occurred_at",
]

# ---------------------------------------------------------------------------
# Import constants
# ---------------------------------------------------------------------------

MAX_IMPORT_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_IMPORT_ROWS = 5000


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def format_csv_value(value: Any) -> str:
    """Convert a Python value to a CSV-safe string representation."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return "|".join(format_csv_value(item) for item in value)
    return str(value)


def build_csv_bytes(headers: list[str], rows: list[dict]) -> bytes:
    """Build a complete CSV file as bytes from *headers* and *rows*.

    This is intentionally **not** streaming – CRM datasets are small, and
    streaming causes SQLAlchemy session-lifetime bugs with FastAPI.
    """
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="utf-8", newline="")

    writer = csv.writer(wrapper)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(format_csv_value(row.get(h)) for h in headers)

    wrapper.flush()
    wrapper.detach()  # release the underlying BytesIO without closing it
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_csv_upload(
    contents: bytes,
    required_headers: list[str],
    optional_headers: list[str] | None = None,
    max_rows: int = 5000,
) -> list[dict[str, str]]:
    """Parse an uploaded CSV file and return validated row dicts.

    * Uses ``utf-8-sig`` encoding to handle the BOM that Excel adds.
    * Validates that every *required_headers* column is present.
    * Accepts *optional_headers* columns if they exist in the file.
    * Extra columns not in either list are silently ignored.
    * Enforces a *max_rows* limit to prevent oversized imports.

    Raises ``ValueError`` with a human-readable message on problems.
    """
    if not contents or not contents.strip():
        raise ValueError("The uploaded CSV file is empty.")

    text = contents.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise ValueError("The uploaded CSV file is empty.")

    actual_headers = {h.strip() for h in reader.fieldnames}
    missing = [h for h in required_headers if h not in actual_headers]
    if missing:
        raise ValueError(
            f"Missing required CSV headers: {', '.join(sorted(missing))}"
        )

    # Determine which optional headers are actually present in the file
    _optional = optional_headers or []
    present_optional = [h for h in _optional if h in actual_headers]
    all_headers = list(required_headers) + present_optional

    rows: list[dict[str, str]] = []
    for idx, raw_row in enumerate(reader, start=1):
        if idx > max_rows:
            raise ValueError(
                f"CSV file exceeds the maximum of {max_rows} data rows."
            )
        row = {
            h: (raw_row.get(h) or "").strip()
            for h in all_headers
        }
        rows.append(row)

    return rows


def parse_pipe_delimited(value: str) -> list[str]:
    """Split a pipe-delimited string, stripping whitespace and empties."""
    if not value or not value.strip():
        return []
    return [part.strip() for part in value.split("|") if part.strip()]


def parse_datetime_or_none(value: str) -> datetime | None:
    """Parse an ISO 8601 datetime string, returning *None* for blanks.

    Naive datetimes are assumed to be UTC.
    """
    if not value or not value.strip():
        return None

    value = value.strip()
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid datetime value: '{value}'") from exc

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_filter_datetime(value: str | None, *, upper_bound: bool) -> datetime | None:
    """Parse an ISO 8601 datetime string for a CRM filter bound.

    A *bare date* (``YYYY-MM-DD``, no time) used as an inclusive ``upper_bound``
    is extended to end-of-day (``23:59:59.999999``) so the whole day is covered.
    An explicit datetime is honored verbatim, even at midnight -- so callers can
    target ``...T00:00:00`` precisely. Naive datetimes are assumed UTC.
    """
    if value is None or not value.strip():
        return None
    parsed = parse_datetime_or_none(value)
    if parsed is not None and upper_bound and is_date_only(value):
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


def parse_enum_or_none(value: str, enum_class: type) -> Any | None:
    """Parse a string to an enum member by value (case-insensitive).

    Returns *None* for empty/whitespace-only input.
    """
    if not value or not value.strip():
        return None

    value = value.strip()
    value_lower = value.lower()
    for member in enum_class:
        if str(member.value).lower() == value_lower:
            return member

    valid = ", ".join(str(m.value) for m in enum_class)
    raise ValueError(
        f"Invalid value '{value}' for {enum_class.__name__}. "
        f"Valid options: {valid}"
    )
