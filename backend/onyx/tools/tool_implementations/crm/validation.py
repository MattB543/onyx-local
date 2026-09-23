"""Strict input validation shared by the CRM write tools.

Every check raises ToolCallException with a message that names the offending
fields or values, so the model can correct the call instead of having input
silently dropped.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator
from contextlib import contextmanager
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
from onyx.tools.models import ToolCallException


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


def parse_uuid_list(value: Any, field_name: str) -> list[UUID]:
    """A list of UUID strings; null, blank, or malformed entries are errors.
    Repeated IDs collapse."""
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
    return list(dict.fromkeys(parsed))


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


@contextmanager
def crm_write_errors(action: str) -> Iterator[None]:
    """Turn database errors from a CRM write into model-facing tool errors.
    The caller's session rolls back, so nothing from the call is saved."""
    try:
        yield
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
