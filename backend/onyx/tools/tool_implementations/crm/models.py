from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.db.crm import (
    get_contact_names,
    get_contact_owner_ids,
    get_contact_tags,
    get_interaction_attendees,
    get_organization_names,
    get_user_names_and_emails,
)
from onyx.db.models import (
    CrmContact,
    CrmInteraction,
    CrmInteractionAttendee,
    CrmOrganization,
    CrmTag,
)
from onyx.file_store.utils import build_frontend_file_url
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CrmCreateToolDelta,
    CrmGetToolDelta,
    CrmListToolDelta,
    CrmLogInteractionToolDelta,
    CrmSearchToolDelta,
    CrmUpdateToolDelta,
    Packet,
)
from onyx.tools.models import ToolCallException, ToolResponse
from onyx.tools.tool_implementations.payload_utils import as_llm_json as as_llm_json
from onyx.tools.tool_implementations.payload_utils import (
    compact_tool_payload_for_model as compact_tool_payload_for_model,
)

E = TypeVar("E", bound=Enum)

REQUIRED_CRM_TABLES = {
    "crm_settings",
    "crm_organization",
    "crm_contact",
    "crm_contact_owner",
    "crm_interaction",
    "crm_interaction_attendee",
    "crm_tag",
    "crm_contact__tag",
    "crm_organization__tag",
}


CrmToolDelta = (
    CrmCreateToolDelta
    | CrmGetToolDelta
    | CrmListToolDelta
    | CrmLogInteractionToolDelta
    | CrmSearchToolDelta
    | CrmUpdateToolDelta
)


def crm_tool_response(
    emitter: Emitter,
    placement: Placement,
    payload: dict[str, Any],
    delta_type: type[CrmToolDelta],
) -> ToolResponse:
    """Stream the compacted payload and return it as the tool response. The
    model sees the same compacted payload as the UI."""
    compact_payload = compact_tool_payload_for_model(payload)
    emitter.emit(Packet(placement=placement, obj=delta_type(payload=compact_payload)))
    return ToolResponse(
        rich_response=json.dumps(payload, default=str),
        llm_facing_response=as_llm_json(compact_payload, already_compacted=True),
    )


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


def parse_enum_maybe(enum_cls: type[E], value: Any, field_name: str) -> E | None:
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


def parse_stage_maybe(
    value: Any,
    *,
    allowed_stages: list[str],
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ToolCallException(
            message=f"Invalid type for stage field {field_name}: {type(value)}",
            llm_facing_message=f"'{field_name}' must be a string.",
        )

    normalized = value.strip().lower()
    if not normalized:
        raise ToolCallException(
            message=f"Invalid empty stage value for {field_name}",
            llm_facing_message=f"'{field_name}' cannot be empty.",
        )

    if normalized in allowed_stages:
        return normalized

    raise ToolCallException(
        message=f"Invalid stage value for {field_name}: {value}",
        llm_facing_message=f"'{field_name}' must be one of: {', '.join(allowed_stages)}.",
    )


def contact_full_name(contact: CrmContact) -> str:
    first_name = (contact.first_name or "").strip()
    last_name = (contact.last_name or "").strip()
    return " ".join([part for part in [first_name, last_name] if part]).strip()


@dataclass
class CrmNames:
    """Display names for the users, contacts and organizations that one tool
    response refers to, loaded in one batch query per kind."""

    users: dict[UUID, tuple[str | None, str]] = field(default_factory=dict)
    contacts: dict[UUID, str] = field(default_factory=dict)
    organizations: dict[UUID, str] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        db_session: Session,
        *,
        contacts: Iterable[CrmContact] = (),
        owner_ids: Iterable[UUID] = (),
        interactions: Iterable[CrmInteraction] = (),
        attendees: Iterable[CrmInteractionAttendee] = (),
    ) -> CrmNames:
        user_ids = set(owner_ids)
        contact_ids: set[UUID] = set()
        organization_ids = {
            contact.organization_id for contact in contacts if contact.organization_id
        }
        for interaction in interactions:
            if interaction.contact_id:
                contact_ids.add(interaction.contact_id)
            if interaction.organization_id:
                organization_ids.add(interaction.organization_id)
            if interaction.logged_by:
                user_ids.add(interaction.logged_by)
        for attendee in attendees:
            if attendee.user_id:
                user_ids.add(attendee.user_id)
            if attendee.contact_id:
                contact_ids.add(attendee.contact_id)
        return cls(
            users=get_user_names_and_emails(user_ids, db_session),
            contacts=get_contact_names(contact_ids, db_session),
            organizations=get_organization_names(organization_ids, db_session),
        )

    def user_name(self, user_id: UUID | None) -> str | None:
        if user_id is None or user_id not in self.users:
            return None
        personal_name, email = self.users[user_id]
        return personal_name or email

    def user_ref(self, user_id: UUID) -> dict[str, Any]:
        personal_name, email = self.users.get(user_id, (None, None))
        return {"id": str(user_id), "name": personal_name, "email": email}


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
    owner_ids: list[UUID] | None = None,
    tags: list[CrmTag] | None = None,
    names: CrmNames | None = None,
) -> dict[str, Any]:
    names = names or CrmNames()
    return {
        "id": str(contact.id),
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "full_name": contact_full_name(contact),
        "email": contact.email,
        "phone": contact.phone,
        "title": contact.title,
        "organization_id": (
            str(contact.organization_id) if contact.organization_id else None
        ),
        "organization_name": (
            names.organizations.get(contact.organization_id)
            if contact.organization_id
            else None
        ),
        "owner_ids": [str(owner_id) for owner_id in (owner_ids or [])],
        "owners": [names.user_ref(owner_id) for owner_id in (owner_ids or [])],
        "source": contact.source.value if contact.source else None,
        "status": contact.status,
        "category": contact.category,
        "party_affiliation": contact.party_affiliation,
        "us_state": contact.us_state,
        "principal": contact.principal,
        "notes": contact.notes,
        "linkedin_url": contact.linkedin_url,
        "location": contact.location,
        "profile_picture_file_id": contact.profile_picture_file_id,
        "profile_picture_url": (
            build_frontend_file_url(contact.profile_picture_file_id)
            if contact.profile_picture_file_id
            else None
        ),
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
        "created_at": (
            organization.created_at.isoformat() if organization.created_at else None
        ),
        "updated_at": (
            organization.updated_at.isoformat() if organization.updated_at else None
        ),
        "tags": [serialize_tag(tag) for tag in (tags or [])],
    }


def serialize_interaction_attendee(
    attendee: CrmInteractionAttendee,
    names: CrmNames | None = None,
) -> dict[str, Any]:
    names = names or CrmNames()
    return {
        "id": attendee.id,
        "user_id": str(attendee.user_id) if attendee.user_id else None,
        "contact_id": str(attendee.contact_id) if attendee.contact_id else None,
        "display_name": (
            names.contacts.get(attendee.contact_id)
            if attendee.contact_id
            else names.user_name(attendee.user_id)
        ),
        "role": attendee.role.value if attendee.role else None,
        "created_at": attendee.created_at.isoformat() if attendee.created_at else None,
    }


def serialize_interaction(
    interaction: CrmInteraction,
    *,
    attendees: list[CrmInteractionAttendee] | None = None,
    names: CrmNames | None = None,
) -> dict[str, Any]:
    names = names or CrmNames()
    return {
        "id": str(interaction.id),
        "contact_id": str(interaction.contact_id) if interaction.contact_id else None,
        "contact_name": (
            names.contacts.get(interaction.contact_id)
            if interaction.contact_id
            else None
        ),
        "organization_id": (
            str(interaction.organization_id) if interaction.organization_id else None
        ),
        "organization_name": (
            names.organizations.get(interaction.organization_id)
            if interaction.organization_id
            else None
        ),
        "logged_by": str(interaction.logged_by) if interaction.logged_by else None,
        "logged_by_name": names.user_name(interaction.logged_by),
        "type": interaction.type.value if interaction.type else None,
        "title": interaction.title,
        "summary": interaction.summary,
        "occurred_at": (
            interaction.occurred_at.isoformat() if interaction.occurred_at else None
        ),
        "created_at": (
            interaction.created_at.isoformat() if interaction.created_at else None
        ),
        "updated_at": (
            interaction.updated_at.isoformat() if interaction.updated_at else None
        ),
        "attendees": [
            serialize_interaction_attendee(attendee, names)
            for attendee in (attendees or [])
        ],
    }


def serialize_contacts(
    db_session: Session, contacts: list[CrmContact]
) -> list[dict[str, Any]]:
    """Contacts with tags, owners and names (one name batch per call)."""
    owner_ids = {
        contact.id: get_contact_owner_ids(contact.id, db_session)
        for contact in contacts
    }
    names = CrmNames.load(
        db_session,
        contacts=contacts,
        owner_ids=(owner for owners in owner_ids.values() for owner in owners),
    )
    return [
        serialize_contact(
            contact,
            owner_ids=owner_ids[contact.id],
            tags=get_contact_tags(contact.id, db_session),
            names=names,
        )
        for contact in contacts
    ]


def serialize_interactions(
    db_session: Session, interactions: list[CrmInteraction]
) -> list[dict[str, Any]]:
    """Interactions with attendees and names (one name batch per call)."""
    attendees = {
        interaction.id: get_interaction_attendees(interaction.id, db_session)
        for interaction in interactions
    }
    names = CrmNames.load(
        db_session,
        interactions=interactions,
        attendees=(row for rows in attendees.values() for row in rows),
    )
    return [
        serialize_interaction(
            interaction, attendees=attendees[interaction.id], names=names
        )
        for interaction in interactions
    ]
