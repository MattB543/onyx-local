from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import get_contact_by_id
from onyx.db.crm import get_contact_tags
from onyx.db.crm import get_interaction_attendees
from onyx.db.crm import get_interaction_by_id
from onyx.db.crm import get_organization_by_id
from onyx.db.crm import get_organization_tags
from onyx.db.crm import get_tag_by_id
from onyx.db.crm import list_interactions
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CrmGetToolDelta
from onyx.server.query_and_chat.streaming_models import CrmGetToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.crm.models import as_llm_json
from onyx.tools.tool_implementations.crm.models import compact_tool_payload_for_model
from onyx.tools.tool_implementations.crm.models import is_crm_schema_available
from onyx.tools.tool_implementations.crm.models import parse_uuid_maybe
from onyx.tools.tool_implementations.crm.models import serialize_contact
from onyx.tools.tool_implementations.crm.models import serialize_interaction
from onyx.tools.tool_implementations.crm.models import serialize_organization
from onyx.tools.tool_implementations.crm.models import serialize_tag


CRM_GET_ENTITY_TYPES = {"contact", "organization", "interaction", "tag"}
CRM_GET_INCLUDE_OPTIONS = {"tags", "interactions", "organization", "attendees", "contacts"}


class CrmGetTool(Tool[None]):
    NAME = "crm_get"
    DISPLAY_NAME = "CRM Get"
    DESCRIPTION = (
        "Fetch the full details of a specific CRM entity by its UUID. Use this after finding an "
        "entity via crm_search or crm_list to get complete information. Optionally include related "
        "data: 'tags' for a contact/org's tags, 'interactions' for recent interactions, "
        "'organization' to expand a contact's linked org, 'attendees' for an interaction's attendees, "
        "'contacts' to list contacts belonging to an organization."
    )

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        emitter: Emitter,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
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
                        "entity_type": {
                            "type": "string",
                            "enum": sorted(list(CRM_GET_ENTITY_TYPES)),
                            "description": "The type of CRM entity to retrieve.",
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "The UUID of the entity to retrieve.",
                        },
                        "include": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": sorted(list(CRM_GET_INCLUDE_OPTIONS)),
                            },
                            "description": (
                                "Related data to include. Options: "
                                "'tags' (for contacts/orgs), "
                                "'interactions' (recent interactions for a contact/org), "
                                "'organization' (expand a contact's linked org), "
                                "'attendees' (for an interaction), "
                                "'contacts' (list contacts at an org)."
                            ),
                        },
                    },
                    "required": ["entity_type", "entity_id"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmGetToolStart()))

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        entity_type_raw = llm_kwargs.get("entity_type")
        if not isinstance(entity_type_raw, str):
            raise ToolCallException(
                message=f"Missing/invalid entity_type in {self.name}",
                llm_facing_message="'entity_type' must be one of: contact, organization, interaction, tag.",
            )

        entity_type = entity_type_raw.strip().lower()
        if entity_type not in CRM_GET_ENTITY_TYPES:
            raise ToolCallException(
                message=f"Unsupported entity_type in {self.name}: {entity_type}",
                llm_facing_message="'entity_type' must be one of: contact, organization, interaction, tag.",
            )

        entity_id = parse_uuid_maybe(llm_kwargs.get("entity_id"), "entity_id")
        if not entity_id:
            raise ToolCallException(
                message=f"Missing/invalid entity_id in {self.name}",
                llm_facing_message="'entity_id' must be a valid UUID.",
            )

        include_raw = llm_kwargs.get("include", [])
        if not isinstance(include_raw, list):
            include_raw = []
        includes = {
            s.strip().lower()
            for s in include_raw
            if isinstance(s, str) and s.strip().lower() in CRM_GET_INCLUDE_OPTIONS
        }

        with self._session_factory() as db_session:
            if entity_type == "contact":
                payload = self._get_contact(db_session, entity_id, includes)
            elif entity_type == "organization":
                payload = self._get_organization(db_session, entity_id, includes)
            elif entity_type == "interaction":
                payload = self._get_interaction(db_session, entity_id, includes)
            else:
                payload = self._get_tag(db_session, entity_id)

        compact_payload = compact_tool_payload_for_model(payload)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CrmGetToolDelta(payload=compact_payload),
            )
        )

        rich_response = json.dumps(payload, default=str)
        llm_response = as_llm_json(compact_payload, already_compacted=True)
        return ToolResponse(
            rich_response=rich_response,
            llm_facing_response=llm_response,
        )

    def _get_contact(
        self,
        db_session: Session,
        entity_id: Any,
        includes: set[str],
    ) -> dict[str, Any]:
        contact = get_contact_by_id(entity_id, db_session)
        if contact is None:
            raise ToolCallException(
                message=f"Contact not found: {entity_id}",
                llm_facing_message="Could not find a contact with that ID.",
            )

        tags = get_contact_tags(contact.id, db_session)
        result: dict[str, Any] = {
            "status": "ok",
            "entity_type": "contact",
            "contact": serialize_contact(contact, tags=tags),
        }

        if "organization" in includes and contact.organization_id:
            org = get_organization_by_id(contact.organization_id, db_session)
            if org:
                org_tags = get_organization_tags(org.id, db_session)
                result["organization"] = serialize_organization(org, tags=org_tags)

        if "interactions" in includes:
            interactions, total = list_interactions(
                db_session=db_session,
                page_num=0,
                page_size=10,
                contact_id=contact.id,
            )
            result["recent_interactions"] = {
                "total": total,
                "items": [
                    serialize_interaction(
                        i, attendees=get_interaction_attendees(i.id, db_session)
                    )
                    for i in interactions
                ],
            }

        return result

    def _get_organization(
        self,
        db_session: Session,
        entity_id: Any,
        includes: set[str],
    ) -> dict[str, Any]:
        org = get_organization_by_id(entity_id, db_session)
        if org is None:
            raise ToolCallException(
                message=f"Organization not found: {entity_id}",
                llm_facing_message="Could not find an organization with that ID.",
            )

        tags = get_organization_tags(org.id, db_session)
        result: dict[str, Any] = {
            "status": "ok",
            "entity_type": "organization",
            "organization": serialize_organization(org, tags=tags),
        }

        if "contacts" in includes:
            from onyx.db.crm import list_contacts

            contacts, total = list_contacts(
                db_session=db_session,
                page_num=0,
                page_size=10,
                organization_id=org.id,
            )
            result["contacts"] = {
                "total": total,
                "items": [
                    serialize_contact(c, tags=get_contact_tags(c.id, db_session))
                    for c in contacts
                ],
            }

        if "interactions" in includes:
            interactions, total = list_interactions(
                db_session=db_session,
                page_num=0,
                page_size=10,
                organization_id=org.id,
            )
            result["recent_interactions"] = {
                "total": total,
                "items": [
                    serialize_interaction(
                        i, attendees=get_interaction_attendees(i.id, db_session)
                    )
                    for i in interactions
                ],
            }

        return result

    def _get_interaction(
        self,
        db_session: Session,
        entity_id: Any,
        includes: set[str],  # noqa: ARG002
    ) -> dict[str, Any]:
        interaction = get_interaction_by_id(entity_id, db_session)
        if interaction is None:
            raise ToolCallException(
                message=f"Interaction not found: {entity_id}",
                llm_facing_message="Could not find an interaction with that ID.",
            )

        attendees = get_interaction_attendees(interaction.id, db_session)
        result: dict[str, Any] = {
            "status": "ok",
            "entity_type": "interaction",
            "interaction": serialize_interaction(interaction, attendees=attendees),
        }

        # Always include linked contact/org details for context
        if interaction.contact_id:
            contact = get_contact_by_id(interaction.contact_id, db_session)
            if contact:
                result["contact"] = serialize_contact(
                    contact, tags=get_contact_tags(contact.id, db_session)
                )

        if interaction.organization_id:
            org = get_organization_by_id(interaction.organization_id, db_session)
            if org:
                result["organization"] = serialize_organization(
                    org, tags=get_organization_tags(org.id, db_session)
                )

        return result

    def _get_tag(
        self,
        db_session: Session,
        entity_id: Any,
    ) -> dict[str, Any]:
        tag = get_tag_by_id(entity_id, db_session)
        if tag is None:
            raise ToolCallException(
                message=f"Tag not found: {entity_id}",
                llm_facing_message="Could not find a tag with that ID.",
            )

        return {
            "status": "ok",
            "entity_type": "tag",
            "tag": serialize_tag(tag),
        }
