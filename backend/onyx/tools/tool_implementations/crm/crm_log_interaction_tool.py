from __future__ import annotations

from collections import defaultdict
import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import add_interaction_attendees
from onyx.db.crm import create_interaction
from onyx.db.crm import find_contacts_for_attendee_resolution
from onyx.db.crm import find_users_for_attendee_resolution
from onyx.db.crm import get_contact_by_id
from onyx.db.crm import get_interaction_attendees
from onyx.db.crm import get_organization_by_id
from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmInteractionType
from onyx.db.models import User
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CrmLogInteractionToolDelta
from onyx.server.query_and_chat.streaming_models import CrmLogInteractionToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.crm.models import as_llm_json
from onyx.tools.tool_implementations.crm.models import compact_tool_payload_for_model
from onyx.tools.tool_implementations.crm.models import contact_full_name
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
                                        "enum": [member.value for member in CrmAttendeeRole],
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

    def _serialize_contact_candidate(self, contact: Any) -> dict[str, Any]:
        return {
            "entity_type": "contact",
            "id": str(contact.id),
            "label": contact_full_name(contact) or contact.email or str(contact.id),
            "email": contact.email,
        }

    def _serialize_user_candidate(self, user: Any) -> dict[str, Any]:
        return {
            "entity_type": "user",
            "id": str(user.id),
            "label": (user.personal_name or user.email or str(user.id)),
            "email": user.email,
        }

    def _resolve_attendee_token(
        self,
        token: str,
        db_session: Session,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
        normalized = token.strip()
        if not normalized:
            return None, [], "empty"

        normalized_lower = normalized.lower()
        contacts = find_contacts_for_attendee_resolution(
            db_session=db_session,
            token=normalized,
            max_results=5,
        )
        users = find_users_for_attendee_resolution(
            db_session=db_session,
            token=normalized,
            max_results=5,
        )

        # Priority 1: exact contact email
        exact_contact_email = next(
            (
                contact
                for contact in contacts
                if contact.email and contact.email.lower() == normalized_lower
            ),
            None,
        )
        if exact_contact_email:
            return (
                {
                    "user_id": None,
                    "contact_id": exact_contact_email.id,
                },
                [],
                None,
            )

        # Priority 2: exact user email
        exact_user_email = next(
            (user for user in users if user.email and user.email.lower() == normalized_lower),
            None,
        )
        if exact_user_email:
            return (
                {
                    "user_id": exact_user_email.id,
                    "contact_id": None,
                },
                [],
                None,
            )

        # Priority 3: exact contact full-name
        exact_contact_name_matches = [
            contact
            for contact in contacts
            if contact_full_name(contact).lower() == normalized_lower
        ]
        if len(exact_contact_name_matches) == 1:
            return (
                {
                    "user_id": None,
                    "contact_id": exact_contact_name_matches[0].id,
                },
                [],
                None,
            )
        if len(exact_contact_name_matches) > 1:
            return (
                None,
                [
                    self._serialize_contact_candidate(contact)
                    for contact in exact_contact_name_matches
                ],
                "ambiguous_exact_contact_name",
            )

        # Priority 4: fuzzy contact name
        fuzzy_contact_matches = []
        for contact in contacts:
            candidate_name = contact_full_name(contact).lower()
            candidate_email = (contact.email or "").lower()
            if normalized_lower in candidate_name or normalized_lower in candidate_email:
                fuzzy_contact_matches.append(contact)

        if len(fuzzy_contact_matches) == 1:
            return (
                {
                    "user_id": None,
                    "contact_id": fuzzy_contact_matches[0].id,
                },
                [],
                None,
            )
        if len(fuzzy_contact_matches) > 1:
            return (
                None,
                [self._serialize_contact_candidate(contact) for contact in fuzzy_contact_matches],
                "ambiguous_fuzzy_contact_name",
            )

        # Priority 5: fuzzy user display/email
        fuzzy_user_matches = []
        for user in users:
            candidate_name = (user.personal_name or "").lower()
            candidate_email = (user.email or "").lower()
            if normalized_lower in candidate_name or normalized_lower in candidate_email:
                fuzzy_user_matches.append(user)

        if len(fuzzy_user_matches) == 1:
            return (
                {
                    "user_id": fuzzy_user_matches[0].id,
                    "contact_id": None,
                },
                [],
                None,
            )
        if len(fuzzy_user_matches) > 1:
            return (
                None,
                [self._serialize_user_candidate(user) for user in fuzzy_user_matches],
                "ambiguous_fuzzy_user_name",
            )

        return None, [], "not_found"

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
            if organization_id and get_organization_by_id(organization_id, db_session) is None:
                raise ToolCallException(
                    message=f"Organization not found: {organization_id}",
                    llm_facing_message="Could not find the provided organization_id.",
                )
            if primary_contact_id and get_contact_by_id(primary_contact_id, db_session) is None:
                raise ToolCallException(
                    message=f"Primary contact not found: {primary_contact_id}",
                    llm_facing_message="Could not find the provided primary_contact_id.",
                )

            resolved_attendees: list[dict[str, Any]] = []
            needs_confirmation: list[dict[str, Any]] = []
            resolution_details: list[dict[str, Any]] = []

            for attendee in attendees_to_resolve:
                role = CrmAttendeeRole.ATTENDEE
                token_for_resolution: str | None = None
                user_id: UUID | None = None
                attendee_contact_id: UUID | None = None

                if isinstance(attendee, str):
                    token_for_resolution = attendee
                elif isinstance(attendee, dict):
                    role_raw = attendee.get("role")
                    parsed_role = parse_enum_maybe(CrmAttendeeRole, role_raw, "attendees[].role")
                    if isinstance(parsed_role, CrmAttendeeRole):
                        role = parsed_role

                    user_id = parse_uuid_maybe(attendee.get("user_id"), "attendees[].user_id")
                    attendee_contact_id = parse_uuid_maybe(
                        attendee.get("contact_id"),
                        "attendees[].contact_id",
                    )

                    if user_id and attendee_contact_id:
                        needs_confirmation.append(
                            {
                                "input": attendee,
                                "reason": "invalid_both_user_and_contact_provided",
                                "candidates": [],
                            }
                        )
                        continue

                    token_for_resolution = (
                        attendee.get("email")
                        or attendee.get("name")
                        or attendee.get("id")
                        or attendee.get("token")
                    )
                else:
                    needs_confirmation.append(
                        {
                            "input": str(attendee),
                            "reason": "invalid_attendee_item_type",
                            "candidates": [],
                        }
                    )
                    continue

                if user_id:
                    user = db_session.get(User, user_id)
                    if user is None:
                        needs_confirmation.append(
                            {
                                "input": str(user_id),
                                "reason": "user_not_found",
                                "candidates": [],
                            }
                        )
                        continue
                    resolved_attendees.append(
                        {
                            "user_id": user.id,
                            "contact_id": None,
                            "role": role,
                        }
                    )
                    resolution_details.append(
                        {
                            "input": str(user_id),
                            "matched_type": "user",
                            "matched_label": user.personal_name or user.email or str(user.id),
                            "confidence": "exact_id",
                        }
                    )
                    continue

                if attendee_contact_id:
                    attendee_contact = get_contact_by_id(attendee_contact_id, db_session)
                    if attendee_contact is None:
                        needs_confirmation.append(
                            {
                                "input": str(attendee_contact_id),
                                "reason": "contact_not_found",
                                "candidates": [],
                            }
                        )
                        continue
                    resolved_attendees.append(
                        {
                            "user_id": None,
                            "contact_id": attendee_contact.id,
                            "role": role,
                        }
                    )
                    resolution_details.append(
                        {
                            "input": str(attendee_contact_id),
                            "matched_type": "contact",
                            "matched_label": contact_full_name(attendee_contact) or attendee_contact.email or str(attendee_contact.id),
                            "confidence": "exact_id",
                        }
                    )
                    continue

                if token_for_resolution and isinstance(token_for_resolution, str):
                    resolved, candidates, reason = self._resolve_attendee_token(
                        token=token_for_resolution,
                        db_session=db_session,
                    )
                    if resolved:
                        resolved_attendees.append(
                            {
                                "user_id": resolved["user_id"],
                                "contact_id": resolved["contact_id"],
                                "role": role,
                            }
                        )
                        # Determine matched label for resolution details
                        if resolved["contact_id"]:
                            matched_contact = get_contact_by_id(resolved["contact_id"], db_session)
                            matched_label = (
                                contact_full_name(matched_contact) if matched_contact else str(resolved["contact_id"])
                            )
                            matched_type = "contact"
                        else:
                            matched_user = db_session.get(User, resolved["user_id"])
                            matched_label = (
                                (matched_user.personal_name or matched_user.email or str(matched_user.id))
                                if matched_user
                                else str(resolved["user_id"])
                            )
                            matched_type = "user"

                        # Map None reason to a confidence level
                        confidence = "fuzzy_match"
                        if "@" in token_for_resolution:
                            confidence = "exact_email"
                        elif token_for_resolution.lower() == matched_label.lower():
                            confidence = "exact_name"

                        resolution_details.append(
                            {
                                "input": token_for_resolution,
                                "matched_type": matched_type,
                                "matched_label": matched_label,
                                "confidence": confidence,
                            }
                        )
                    else:
                        needs_confirmation.append(
                            {
                                "input": token_for_resolution,
                                "reason": reason or "unresolved",
                                "candidates": candidates,
                            }
                        )
                else:
                    needs_confirmation.append(
                        {
                            "input": attendee,
                            "reason": "missing_attendee_identifier",
                            "candidates": [],
                        }
                    )

            deduped_attendees: dict[tuple[UUID | None, UUID | None], CrmAttendeeRole] = {}
            for attendee in resolved_attendees:
                key = (attendee["user_id"], attendee["contact_id"])
                existing_role = deduped_attendees.get(key)
                next_role = attendee["role"]
                if existing_role is None:
                    deduped_attendees[key] = next_role
                elif existing_role != CrmAttendeeRole.ORGANIZER and next_role == CrmAttendeeRole.ORGANIZER:
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

            if needs_confirmation:
                payload = {
                    "status": "needs_confirmation",
                    "message": "Some attendees could not be uniquely resolved.",
                    "needs_confirmation": needs_confirmation,
                    "resolved_attendees": [
                        {
                            "user_id": str(user_id) if user_id else None,
                            "contact_id": str(attendee_contact_id) if attendee_contact_id else None,
                            "role": role.value,
                        }
                        for (user_id, attendee_contact_id), role in deduped_attendees.items()
                    ],
                }
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
            for (attendee_user_id, attendee_contact_id), role in deduped_attendees.items():
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
