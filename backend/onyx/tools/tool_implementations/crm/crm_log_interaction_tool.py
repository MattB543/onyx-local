from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import add_interaction_attendees
from onyx.db.crm import create_interaction
from onyx.db.crm import get_contact_by_id
from onyx.db.crm import get_interaction_attendees
from onyx.db.crm import get_organization_by_id
from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmInteractionType
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CrmLogInteractionToolDelta
from onyx.server.query_and_chat.streaming_models import CrmLogInteractionToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.crm.attendee_resolution import resolve_attendees
from onyx.tools.tool_implementations.crm.models import as_llm_json
from onyx.tools.tool_implementations.crm.models import compact_tool_payload_for_model
from onyx.tools.tool_implementations.crm.models import is_crm_schema_available
from onyx.tools.tool_implementations.crm.models import parse_datetime_maybe
from onyx.tools.tool_implementations.crm.models import parse_enum_maybe
from onyx.tools.tool_implementations.crm.models import parse_uuid_maybe
from onyx.tools.tool_implementations.crm.models import serialize_interaction

ATTENDEES_NOT_PROVIDED = object()


class CrmLogInteractionTool(Tool[None]):
    NAME = "crm_log_interaction"
    DISPLAY_NAME = "CRM Log Interaction"
    DESCRIPTION = (
        "Log a call, meeting, email, note, or event in the CRM. Link it to a contact_id and/or "
        "organization_id for context. Include attendees by email or name — the system will try to "
        "match them to existing contacts and team members and report what matched. Always include "
        "a summary capturing key discussion points and action items. Set occurred_at if the "
        "interaction happened in the past."
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
                        "primary_contact_id": {
                            "type": "string",
                            "description": "UUID of the primary contact if different from contact_id. Auto-added as attendee.",
                        },
                        "attendees": {
                            "type": "array",
                            "description": (
                                "People who attended. Each item can provide an email or name "
                                "for automatic resolution to an existing contact or team member. "
                                "The system will report what matched and at what confidence level. "
                                "If omitted, defaults to the invoking user plus primary contact; "
                                "pass [] for explicitly no attendees."
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
        organization_id = parse_uuid_maybe(
            llm_kwargs.get("organization_id"), "organization_id"
        )
        primary_contact_id = parse_uuid_maybe(
            llm_kwargs.get("primary_contact_id"), "primary_contact_id"
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

        with self._session_factory() as db_session:
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
            if (
                primary_contact_id
                and get_contact_by_id(primary_contact_id, db_session) is None
            ):
                raise ToolCallException(
                    message=f"Primary contact not found: {primary_contact_id}",
                    llm_facing_message="Could not find the provided primary_contact_id.",
                )

            resolved_attendees, needs_confirmation, resolution_details = (
                resolve_attendees(
                    db_session=db_session,
                    attendees_to_resolve=attendees_to_resolve,
                )
            )

            deduped_attendees: dict[
                tuple[UUID | None, UUID | None], CrmAttendeeRole
            ] = {}
            for attendee in resolved_attendees:
                key = (attendee["user_id"], attendee["contact_id"])
                existing_role = deduped_attendees.get(key)
                next_role = attendee["role"]
                if existing_role is None:
                    deduped_attendees[key] = next_role
                elif (
                    existing_role != CrmAttendeeRole.ORGANIZER
                    and next_role == CrmAttendeeRole.ORGANIZER
                ):
                    deduped_attendees[key] = next_role

            # Default attendees only when 'attendees' is omitted entirely.
            # Explicit [] or null means "no attendees".
            effective_primary_contact_id = primary_contact_id or contact_id
            if attendees_were_omitted:
                if actor_user_id is not None:
                    deduped_attendees[(actor_user_id, None)] = CrmAttendeeRole.ORGANIZER

                if contact_id is None:
                    contact_id = effective_primary_contact_id

                if effective_primary_contact_id is not None:
                    key = (None, effective_primary_contact_id)
                    if key not in deduped_attendees:
                        deduped_attendees[key] = CrmAttendeeRole.ATTENDEE

            # Proceed with creating the interaction even when some attendees
            # could not be resolved. Unresolved attendees are reported in the
            # response as a warning so the caller can decide whether to follow
            # up separately and update the interaction with additional attendees.

            interaction = create_interaction(
                db_session=db_session,
                contact_id=contact_id,
                organization_id=organization_id,
                logged_by=actor_user_id,
                interaction_type=interaction_type,
                title=title,
                summary=summary,
                occurred_at=occurred_at,
            )

            user_ids_by_role: dict[CrmAttendeeRole, list[UUID]] = defaultdict(list)
            contact_ids_by_role: dict[CrmAttendeeRole, list[UUID]] = defaultdict(list)
            for (
                attendee_user_id,
                attendee_contact_id,
            ), role in deduped_attendees.items():
                if attendee_user_id is not None:
                    user_ids_by_role[role].append(attendee_user_id)
                if attendee_contact_id is not None:
                    contact_ids_by_role[role].append(attendee_contact_id)

            all_roles = set(user_ids_by_role.keys()) | set(contact_ids_by_role.keys())
            for role in all_roles:
                add_interaction_attendees(
                    db_session=db_session,
                    interaction_id=interaction.id,
                    user_ids=user_ids_by_role.get(role),
                    contact_ids=contact_ids_by_role.get(role),
                    role=role,
                )

            attendees = get_interaction_attendees(interaction.id, db_session)
            payload: dict[str, Any] = {
                "status": "created",
                "interaction": serialize_interaction(interaction, attendees=attendees),
            }
            if resolution_details:
                payload["attendee_resolution"] = resolution_details
            if needs_confirmation:
                payload["unresolved_attendees"] = needs_confirmation

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
