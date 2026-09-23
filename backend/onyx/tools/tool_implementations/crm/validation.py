"""Strict input validation shared by the CRM write tools.

Every check raises ToolCallException with a message that names the offending
fields or values, so the model can correct the call instead of having input
silently dropped.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from psycopg2.extensions import TransactionRollbackError
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from onyx.db.crm import (
    find_assignable_users_by_email,
    get_existing_user_ids,
    get_tags_by_ids,
)
from onyx.db.models import CrmTag
from onyx.file_store.file_store import get_default_file_store
from onyx.tools.models import ToolCallException
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The payload compactor keeps at most 25 array items, so a larger page would
# silently lose rows and break offset paging.
MAX_PAGE_SIZE = 25


def _describe(value: Any) -> str:
    return json.dumps(value, default=str)


def reject_unknown_keys(
    payload: dict[str, Any], allowed: Collection[str], field_name: str
) -> None:
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise ToolCallException(
            message=f"Unknown fields in {field_name}: {unknown}",
            llm_facing_message=(
                f"Unknown field(s) in '{field_name}': {', '.join(unknown)}. "
                f"Allowed: {', '.join(sorted(allowed))}. Nothing was saved."
            ),
        )


def parse_page(args: dict[str, Any], tool_name: str) -> tuple[int, int]:
    """page_num and page_size, with page_size capped at MAX_PAGE_SIZE. The
    response reports the page size actually used."""
    try:
        page_num = max(0, int(args.get("page_num", 0)))
        page_size = min(
            MAX_PAGE_SIZE, max(1, int(args.get("page_size", MAX_PAGE_SIZE)))
        )
    except (TypeError, ValueError):
        raise ToolCallException(
            message=f"Invalid page_num/page_size in {tool_name}",
            llm_facing_message="'page_num' and 'page_size' must be integers.",
        )
    return page_num, page_size


def parse_uuid(value: Any, field_name: str) -> UUID:
    """A UUID string; blank or malformed values are errors, not "no value"."""
    try:
        return UUID(value.strip())
    except (AttributeError, ValueError):
        raise ToolCallException(
            message=f"Invalid UUID for {field_name}: {value!r}",
            llm_facing_message=f"'{field_name}' must be a valid UUID string.",
        )


def parse_uuid_list(value: Any, field_name: str) -> list[UUID]:
    """A list of UUID strings; null, blank, malformed, or repeated entries
    are errors."""
    if not isinstance(value, list):
        raise ToolCallException(
            message=f"{field_name} is not a list: {type(value)}",
            llm_facing_message=f"'{field_name}' must be an array of UUID strings.",
        )
    parsed: list[UUID] = []
    invalid: list[str] = []
    for raw in value:
        try:
            parsed.append(UUID(raw.strip()))
        except (AttributeError, ValueError):
            invalid.append(_describe(raw))
    if invalid:
        raise ToolCallException(
            message=f"Invalid UUIDs in {field_name}: {invalid}",
            llm_facing_message=(
                f"'{field_name}' has invalid UUID entries: {', '.join(invalid)}."
            ),
        )
    repeated = sorted({str(u) for u in parsed if parsed.count(u) > 1})
    if repeated:
        raise ToolCallException(
            message=f"Repeated UUIDs in {field_name}: {repeated}",
            llm_facing_message=(
                f"'{field_name}' lists these IDs more than once: {', '.join(repeated)}."
            ),
        )
    return parsed


def require_tags(
    db_session: Session, tag_ids: list[UUID], field_name: str
) -> list[CrmTag]:
    tags_by_id = get_tags_by_ids(tag_ids, db_session)
    missing = [str(tag_id) for tag_id in tag_ids if tag_id not in tags_by_id]
    if missing:
        raise ToolCallException(
            message=f"Unknown tag IDs in {field_name}: {missing}",
            llm_facing_message=(
                f"'{field_name}' has tag IDs that do not exist: {', '.join(missing)}. "
                "Find tag IDs with crm_list (entity_type 'tag') or crm_search, or "
                "create the tag first with crm_create."
            ),
        )
    return [tags_by_id[tag_id] for tag_id in tag_ids]


def resolve_owner_ids(db_session: Session, value: Any, field_name: str) -> list[UUID]:
    """Owners as a full list. Each entry is a user UUID or a teammate's exact
    email (case-insensitive). null means no owners."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolCallException(
            message=f"{field_name} is not a list: {type(value)}",
            llm_facing_message=(
                f"'{field_name}' must be an array of user UUIDs or teammate emails."
            ),
        )

    entries: list[UUID | str] = []
    errors: list[str] = []
    for raw in value:
        entry = raw.strip() if isinstance(raw, str) else ""
        if "@" in entry:
            entries.append(entry.lower())
            continue
        try:
            entries.append(UUID(entry))
        except ValueError:
            errors.append(f"{_describe(raw)} is not a user UUID or an email")

    user_ids = [entry for entry in entries if isinstance(entry, UUID)]
    existing_ids = get_existing_user_ids(user_ids, db_session)
    errors.extend(
        f"no user has ID {user_id}"
        for user_id in user_ids
        if user_id not in existing_ids
    )

    emails = [entry for entry in entries if isinstance(entry, str)]
    users_by_email = find_assignable_users_by_email(emails, db_session)
    resolved: list[UUID] = []
    for entry in entries:
        if isinstance(entry, UUID):
            resolved.append(entry)
            continue
        matches = users_by_email.get(entry, [])
        if len(matches) == 1:
            resolved.append(matches[0].id)
        elif matches:
            errors.append(f"more than one teammate matches {entry}")
        else:
            errors.append(f"no teammate has the email {entry}")

    if errors:
        raise ToolCallException(
            message=f"Invalid {field_name}: {errors}",
            llm_facing_message=f"Invalid '{field_name}': {'; '.join(errors)}.",
        )
    return list(dict.fromkeys(resolved))


def delete_file_best_effort(file_id: str) -> None:
    try:
        get_default_file_store().delete_file(file_id, error_on_missing=False)
    except Exception:
        logger.exception("Failed to delete CRM file: %s", file_id)


@dataclass
class CrmWrite:
    """Files stored during a write; deleted again if the write fails."""

    stored_file_ids: list[str] = field(default_factory=list)


@contextmanager
def crm_write_errors(action: str) -> Iterator[CrmWrite]:
    """Wrap the write phase of a CRM tool call, up to and including its
    commit. On failure the session rolls back, files stored during the write
    are deleted, and database errors become model-facing tool errors."""
    write = CrmWrite()
    try:
        try:
            yield write
        except BaseException:
            for file_id in write.stored_file_ids:
                delete_file_best_effort(file_id)
            raise
    except ValueError as e:
        raise ToolCallException(
            message=f"CRM {action} validation failed: {e}",
            llm_facing_message=f"{e} Nothing was saved.",
        ) from e
    except IntegrityError as e:
        raise ToolCallException(
            message=f"Constraint violation during CRM {action}: {e}",
            llm_facing_message=(
                f"The {action} conflicts with existing data (for example a duplicate "
                "unique value, or a linked record that was just deleted). Nothing "
                "was saved."
            ),
        ) from e
    except OperationalError as e:
        # Deadlocks and serialization failures roll back cleanly; retry is safe.
        if not isinstance(e.orig, TransactionRollbackError):
            raise
        raise ToolCallException(
            message=f"Retryable database error during CRM {action}: {e}",
            llm_facing_message=(
                f"The {action} collided with another change at the same time and "
                "nothing was saved. Retry the same call."
            ),
        ) from e
