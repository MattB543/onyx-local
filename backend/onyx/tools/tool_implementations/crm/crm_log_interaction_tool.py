from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import (
    create_interaction,
    get_contact_by_id,
    get_interaction_attendees,
    get_organization_by_id,
    replace_interaction_attendees,
)
from onyx.db.enums import CrmAttendeeRole, CrmInteractionType
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CrmLogInteractionToolDelta,
    CrmLogInteractionToolStart,
    Packet,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException, ToolResponse
from onyx.tools.tool_implementations.crm.attendee_resolution import resolve_attendees
from onyx.tools.tool_implementations.crm.models import (
    as_llm_json,
    compact_tool_payload_for_model,
    is_crm_schema_available,
    parse_datetime_maybe,
    parse_enum_maybe,
    parse_uuid_maybe,
    serialize_interaction,
)
from onyx.tools.tool_implementations.crm.validation import (
    crm_write_errors,
    reject_unknown_keys,
)

ATTENDEES_NOT_PROVIDED = object()
# 'type' and 'primary_contact_id' are accepted aliases, not in the schema.
LOG_INTERACTION_FIELDS = (
    "title",
    "interaction_type",
    "type",
    "summary",
    "occurred_at",
    "contact_id",
    "primary_contact_id",
    "organization_id",
    "attendees",
)


def _unresolved_attendee_warning(item: dict[str, Any]) -> str:
    candidates = ", ".join(
        f"{candidate['label']} ({candidate['entity_type']} {candidate['id']})"
        for candidate in item.get("candidates", [])
    )
    warning = (
        f"Attendee {json.dumps(item['input'], default=str)} was not added "
        f"({item['reason']})."
    )
    if candidates:
        warning += f" Candidates: {candidates}."
    return warning


class CrmLogInteractionTool(Tool[None]):
    NAME = "crm_log_interaction"
    DISPLAY_NAME = "CRM Log Interaction"
    DESCRIPTION = (
        "Log a call, meeting, email, note, or event. Link contact_id and/or "
        "organization_id. Give attendees by email or name; the result reports matches "
        "and warns about any it couldn't resolve. Summarize key points and action "
        "items; set occurred_at for past events."
    )

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        emitter: Emitter,
        user_id: str | None,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._user_id = user_id
        self._session_factory = sessionmaker(bind=db_session.get_bind())

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        return is_crm_schema_available(db_session)

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short title for the interaction (e.g. 'Discovery call with Acme Corp').",
                        },
                        "interaction_type": {
                            "type": "string",
                            "enum": [member.value for member in CrmInteractionType],
                            "description": "Type of interaction. Defaults to 'note' if omitted.",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of what happened — key discussion points, decisions, and action items.",
                        },
                        "occurred_at": {
                            "type": "string",
                            "description": "When this interaction happened, as an ISO datetime string. Omit for 'right now'.",
                        },
                        "contact_id": {
                            "type": "string",
                            "description": "UUID of the primary contact for this interaction.",
                        },
                        "organization_id": {
                            "type": "string",
                            "description": "UUID of the organization this interaction relates to.",
                        },
                        "attendees": {
                            "type": "array",
                            "description": (
                                "People who attended, matched to existing contacts or "
                                "teammates. Omit to use the current user plus contact_id; "
                                "[] means no attendees."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "email": {
                                        "type": "string",
                                        "description": "Email address — best way to match an attendee to an existing contact or user.",
                                    },
                                    "name": {
                                        "type": "string",
                                        "description": "Full name — used for fuzzy matching if email is not provided.",
                                    },
                                    "contact_id": {
                                        "type": "string",
                                        "description": "UUID of a known CRM contact. Use if you already have the ID.",
                                    },
                                    "user_id": {
                                        "type": "string",
                                        "description": "UUID of a known team member. Use if you already have the ID.",
                                    },
                                    "role": {
                                        "type": "string",
                                        "enum": [
                                            member.value for member in CrmAttendeeRole
                                        ],
                                        "description": "Role in the interaction. Defaults to 'attendee'.",
                                    },
                                },
                            },
                        },
                    },
                    "required": ["title"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmLogInteractionToolStart()))

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        reject_unknown_keys(
            llm_kwargs, LOG_INTERACTION_FIELDS, "crm_log_interaction arguments"
        )
        title = llm_kwargs.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ToolCallException(
                message=f"Missing title in {self.name}",
                llm_facing_message="'title' is required to log an interaction.",
            )

        interaction_type = parse_enum_maybe(
            CrmInteractionType,
            llm_kwargs.get("interaction_type", llm_kwargs.get("type")),
            "interaction_type",
        )
        if interaction_type is None:
            interaction_type = CrmInteractionType.NOTE

        summary = llm_kwargs.get("summary")
        if summary is not None and not isinstance(summary, str):
            summary = str(summary)

        occurred_at = parse_datetime_maybe(llm_kwargs.get("occurred_at"), "occurred_at")
        contact_id = parse_uuid_maybe(llm_kwargs.get("contact_id"), "contact_id")
        primary_contact_id = parse_uuid_maybe(
            llm_kwargs.get("primary_contact_id"), "primary_contact_id"
        )
        if contact_id and primary_contact_id and contact_id != primary_contact_id:
            raise ToolCallException(
                message=f"Conflicting contact_id and primary_contact_id in {self.name}",
                llm_facing_message=(
                    "'contact_id' and 'primary_contact_id' name different contacts. "
                    "Send only 'contact_id'."
                ),
            )
        contact_id = contact_id or primary_contact_id
        organization_id = parse_uuid_maybe(
            llm_kwargs.get("organization_id"), "organization_id"
        )
        actor_user_id = parse_uuid_maybe(self._user_id, "user_id")

        attendees_raw = llm_kwargs.get("attendees", ATTENDEES_NOT_PROVIDED)
        attendees_were_omitted = attendees_raw is ATTENDEES_NOT_PROVIDED
        if attendees_were_omitted or attendees_raw is None:
            attendees_to_resolve: list[Any] = []
        elif isinstance(attendees_raw, list):
            attendees_to_resolve = attendees_raw
        else:
            raise ToolCallException(
                message=f"Invalid attendees payload in {self.name}: {type(attendees_raw)}",
                llm_facing_message="'attendees' must be an array.",
            )

        with self._session_factory() as db_session, crm_write_errors("log"):
            if contact_id and get_contact_by_id(contact_id, db_session) is None:
                raise ToolCallException(
                    message=f"Contact not found: {contact_id}",
                    llm_facing_message="Could not find the provided contact_id.",
                )
            if (
                organization_id
                and get_organization_by_id(organization_id, db_session) is None
            ):
                raise ToolCallException(
                    message=f"Organization not found: {organization_id}",
                    llm_facing_message="Could not find the provided organization_id.",
                )

            resolved_attendees, unresolved_attendees, resolution_details = (
                resolve_attendees(
                    db_session=db_session,
                    attendees_to_resolve=attendees_to_resolve,
                )
            )
            attendee_tuples: list[tuple[UUID | None, UUID | None, CrmAttendeeRole]] = [
                (attendee["user_id"], attendee["contact_id"], attendee["role"])
                for attendee in resolved_attendees
            ]
            # Default attendees only when 'attendees' is omitted entirely.
            # Explicit [] or null means "no attendees".
            if attendees_were_omitted:
                if actor_user_id is not None:
                    attendee_tuples.append(
                        (actor_user_id, None, CrmAttendeeRole.ORGANIZER)
                    )
                if contact_id is not None:
                    attendee_tuples.append((None, contact_id, CrmAttendeeRole.ATTENDEE))

            # Unresolved attendees do not block the interaction; they are
            # reported as warnings so the caller can follow up with crm_update.
            interaction = create_interaction(
                db_session=db_session,
                contact_id=contact_id,
                organization_id=organization_id,
                logged_by=actor_user_id,
                interaction_type=interaction_type,
                title=title,
                summary=summary,
                occurred_at=occurred_at,
                commit=False,
            )
            replace_interaction_attendees(
                db_session=db_session,
                interaction_id=interaction.id,
                attendees=attendee_tuples,
                commit=False,
            )
            # Commit expires loaded rows, so the serializer re-reads updated_at
            # as the triggers left it.
            db_session.commit()

            payload: dict[str, Any] = {
                "status": "created",
                "interaction": serialize_interaction(
                    interaction,
                    attendees=get_interaction_attendees(interaction.id, db_session),
                ),
            }
            if resolution_details:
                payload["attendee_resolution"] = resolution_details
            if unresolved_attendees:
                payload["warnings"] = [
                    _unresolved_attendee_warning(item) for item in unresolved_attendees
                ]

        compact_payload = compact_tool_payload_for_model(payload)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CrmLogInteractionToolDelta(payload=compact_payload),
            )
        )

        rich_response = json.dumps(payload, default=str)
        llm_response = as_llm_json(compact_payload, already_compacted=True)
        return ToolResponse(
            rich_response=rich_response,
            llm_facing_response=llm_response,
        )
