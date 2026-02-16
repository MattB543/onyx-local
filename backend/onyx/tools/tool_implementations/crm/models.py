from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from onyx.db.models import CrmContact
from onyx.db.models import CrmInteraction
from onyx.db.models import CrmInteractionAttendee
from onyx.db.models import CrmOrganization
from onyx.db.models import CrmTag
from onyx.tools.models import ToolCallException


MAX_COMPACT_STRING_LENGTH = 1200
MAX_COMPACT_ARRAY_ITEMS = 8
MAX_COMPACT_OBJECT_KEYS = 40
TRUNCATION_MARKER_PREFIX = "...[truncated"

REQUIRED_CRM_TABLES = {
    "crm_settings",
    "crm_organization",
    "crm_contact",
    "crm_interaction",
    "crm_interaction_attendee",
    "crm_tag",
    "crm_contact__tag",
    "crm_organization__tag",
}


def compact_tool_payload_for_model(payload: Any) -> Any:
    if isinstance(payload, str):
        if len(payload) <= MAX_COMPACT_STRING_LENGTH:
            return payload
        return payload[:MAX_COMPACT_STRING_LENGTH] + "...[truncated]"

    if isinstance(payload, list):
        compacted_items = [
            compact_tool_payload_for_model(item)
            for item in payload[:MAX_COMPACT_ARRAY_ITEMS]
        ]
        if len(payload) > MAX_COMPACT_ARRAY_ITEMS:
            remaining = len(payload) - MAX_COMPACT_ARRAY_ITEMS
            compacted_items.append(f"{TRUNCATION_MARKER_PREFIX} {remaining} items]")
        return compacted_items

    if isinstance(payload, dict):
        compacted: dict[str, Any] = {}
        items = list(payload.items())
        for idx, (key, value) in enumerate(items):
            if idx >= MAX_COMPACT_OBJECT_KEYS:
                break
            compacted[str(key)] = compact_tool_payload_for_model(value)
        if len(items) > MAX_COMPACT_OBJECT_KEYS:
            remaining = len(items) - MAX_COMPACT_OBJECT_KEYS
            compacted["__truncated_keys"] = (
                f"{TRUNCATION_MARKER_PREFIX} {remaining} keys]"
            )
        return compacted

    return payload


def as_llm_json(payload: dict[str, Any], *, already_compacted: bool = False) -> str:
    compacted = payload if already_compacted else compact_tool_payload_for_model(payload)
    return json.dumps(compacted, default=str)


def is_crm_schema_available(db_session: Session) -> bool:
    inspector = inspect(db_session.get_bind())
    existing_tables = set(inspector.get_table_names())
    return REQUIRED_CRM_TABLES.issubset(existing_tables)


def parse_uuid_maybe(value: Any, field_name: str) -> UUID | None:
    if value is None:
        return None

    if isinstance(value, UUID):
        return value

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return UUID(value)
        except ValueError:
            raise ToolCallException(
                message=f"Invalid UUID for {field_name}: {value}",
                llm_facing_message=f"'{field_name}' must be a valid UUID string.",
            )

    raise ToolCallException(
        message=f"Invalid type for UUID field {field_name}: {type(value)}",
        llm_facing_message=f"'{field_name}' must be a UUID string.",
    )


def parse_datetime_maybe(value: Any, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ToolCallException(
            message=f"Invalid datetime type for {field_name}: {type(value)}",
            llm_facing_message=f"'{field_name}' must be an ISO datetime string.",
        )

    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        raise ToolCallException(
            message=f"Invalid datetime format for {field_name}: {value}",
            llm_facing_message=f"'{field_name}' must be an ISO datetime string.",
        )


def parse_enum_maybe(enum_cls: type[Enum], value: Any, field_name: str) -> Enum | None:
    if value is None:
        return None
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)  # type: ignore[arg-type]
        except ValueError:
            pass

        # Support name-based values ("ACTIVE") for enums persisted with native_enum=False.
        for enum_member in enum_cls:
            if enum_member.name.lower() == value.lower():
                return enum_member

    valid_values = ", ".join([str(member.value) for member in enum_cls])
    raise ToolCallException(
        message=f"Invalid enum value for {field_name}: {value}",
        llm_facing_message=f"'{field_name}' must be one of: {valid_values}.",
    )


def contact_full_name(contact: CrmContact) -> str:
    first_name = (contact.first_name or "").strip()
    last_name = (contact.last_name or "").strip()
    return " ".join([part for part in [first_name, last_name] if part]).strip()


def serialize_tag(tag: CrmTag) -> dict[str, Any]:
    return {
        "id": str(tag.id),
        "name": tag.name,
        "color": tag.color,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


def serialize_contact(
    contact: CrmContact,
    *,
    tags: list[CrmTag] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(contact.id),
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "full_name": contact_full_name(contact),
        "email": contact.email,
        "phone": contact.phone,
        "title": contact.title,
        "organization_id": str(contact.organization_id) if contact.organization_id else None,
        "owner_id": str(contact.owner_id) if contact.owner_id else None,
        "source": contact.source.value if contact.source else None,
        "status": contact.status.value if contact.status else None,
        "notes": contact.notes,
        "linkedin_url": contact.linkedin_url,
        "location": contact.location,
        "created_by": str(contact.created_by) if contact.created_by else None,
        "created_at": contact.created_at.isoformat() if contact.created_at else None,
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
        "tags": [serialize_tag(tag) for tag in (tags or [])],
    }


def serialize_organization(
    organization: CrmOrganization,
    *,
    tags: list[CrmTag] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(organization.id),
        "name": organization.name,
        "website": organization.website,
        "type": organization.type.value if organization.type else None,
        "sector": organization.sector,
        "location": organization.location,
        "size": organization.size,
        "notes": organization.notes,
        "created_by": str(organization.created_by) if organization.created_by else None,
        "created_at": organization.created_at.isoformat() if organization.created_at else None,
        "updated_at": organization.updated_at.isoformat() if organization.updated_at else None,
        "tags": [serialize_tag(tag) for tag in (tags or [])],
    }


def serialize_interaction_attendee(
    attendee: CrmInteractionAttendee,
) -> dict[str, Any]:
    return {
        "id": attendee.id,
        "user_id": str(attendee.user_id) if attendee.user_id else None,
        "contact_id": str(attendee.contact_id) if attendee.contact_id else None,
        "role": attendee.role.value if attendee.role else None,
        "created_at": attendee.created_at.isoformat() if attendee.created_at else None,
    }


def serialize_interaction(
    interaction: CrmInteraction,
    *,
    attendees: list[CrmInteractionAttendee] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(interaction.id),
        "contact_id": str(interaction.contact_id) if interaction.contact_id else None,
        "organization_id": str(interaction.organization_id) if interaction.organization_id else None,
        "logged_by": str(interaction.logged_by) if interaction.logged_by else None,
        "type": interaction.type.value if interaction.type else None,
        "title": interaction.title,
        "summary": interaction.summary,
        "occurred_at": interaction.occurred_at.isoformat() if interaction.occurred_at else None,
        "created_at": interaction.created_at.isoformat() if interaction.created_at else None,
        "updated_at": interaction.updated_at.isoformat() if interaction.updated_at else None,
        "attendees": [
            serialize_interaction_attendee(attendee) for attendee in (attendees or [])
        ],
    }
