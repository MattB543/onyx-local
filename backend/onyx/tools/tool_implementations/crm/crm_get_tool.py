from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import (
    get_contact_by_id,
    get_interaction_by_id,
    get_organization_by_id,
    get_organization_tags,
    get_tag_by_id,
    list_contacts,
    list_interactions,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CrmGetToolDelta,
    CrmGetToolStart,
    Packet,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException, ToolResponse
from onyx.tools.tool_implementations.crm.models import (
    as_llm_json,
    compact_tool_payload_for_model,
    is_crm_schema_available,
    serialize_contacts,
    serialize_interactions,
    serialize_organization,
    serialize_tag,
)
from onyx.tools.tool_implementations.crm.validation import (
    parse_uuid,
    reject_unknown_keys,
)

CRM_GET_ENTITY_TYPES = {"contact", "organization", "interaction", "tag"}
# Related records each entity type can expand (latest 10 of each).
INCLUDES_BY_ENTITY_TYPE: dict[str, tuple[str, ...]] = {
    "contact": ("organization", "interactions"),
    "organization": ("contacts", "interactions"),
    "interaction": (),
    "tag": (),
}
# Always returned; accepted in 'include' as no-ops.
ALWAYS_INCLUDED: dict[str, tuple[str, ...]] = {
    "contact": ("tags",),
    "organization": ("tags",),
    "interaction": ("attendees",),
    "tag": (),
}
CRM_GET_INCLUDE_OPTIONS = sorted(
    {option for options in INCLUDES_BY_ENTITY_TYPE.values() for option in options}
)
RELATED_PAGE_SIZE = 10


class CrmGetTool(Tool[None]):
    NAME = "crm_get"
    DISPLAY_NAME = "CRM Get"
    DESCRIPTION = (
        "Get a CRM record by UUID. Contacts include tags and owners; organizations "
        "include tags; interactions include attendees and their linked contact/org. "
        "Use include for related records (latest 10); use crm_list to see more."
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
                            "enum": sorted(CRM_GET_ENTITY_TYPES),
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "UUID of the record.",
                        },
                        "include": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": CRM_GET_INCLUDE_OPTIONS,
                            },
                            "description": (
                                "Contact: 'organization', 'interactions' (including "
                                "ones it attended). Organization: 'contacts', "
                                "'interactions' (linked to the org itself)."
                            ),
                        },
                    },
                    "required": ["entity_type", "entity_id"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmGetToolStart()))

    def _parse_includes(self, entity_type: str, include_raw: Any) -> set[str]:
        if include_raw is None:
            return set()
        if not isinstance(include_raw, list):
            raise ToolCallException(
                message=f"Invalid include in {self.name}: {include_raw!r}",
                llm_facing_message="'include' must be an array of strings.",
            )
        normalized: list[Any] = [
            value.strip().lower() if isinstance(value, str) else value
            for value in include_raw
        ]
        allowed = INCLUDES_BY_ENTITY_TYPE[entity_type]
        invalid = [
            json.dumps(value)
            for value in normalized
            if value not in allowed and value not in ALWAYS_INCLUDED[entity_type]
        ]
        if invalid:
            raise ToolCallException(
                message=f"Invalid include for {entity_type} in {self.name}: {invalid}",
                llm_facing_message=(
                    f"'include' value(s) {', '.join(invalid)} do not apply to "
                    f"entity_type '{entity_type}'. Allowed: "
                    f"{', '.join(allowed) or 'none'}."
                ),
            )
        return {str(value) for value in normalized if value in allowed}

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        reject_unknown_keys(
            llm_kwargs, ("entity_type", "entity_id", "include"), "crm_get arguments"
        )
        entity_type_raw = llm_kwargs.get("entity_type")
        entity_type = (
            entity_type_raw.strip().lower() if isinstance(entity_type_raw, str) else ""
        )
        if entity_type not in CRM_GET_ENTITY_TYPES:
            raise ToolCallException(
                message=f"Unsupported entity_type in {self.name}: {entity_type_raw}",
                llm_facing_message="'entity_type' must be one of: contact, organization, interaction, tag.",
            )

        entity_id = parse_uuid(llm_kwargs.get("entity_id"), "entity_id")
        includes = self._parse_includes(entity_type, llm_kwargs.get("include"))

        with self._session_factory() as db_session:
            if entity_type == "contact":
                payload = self._get_contact(db_session, entity_id, includes)
            elif entity_type == "organization":
                payload = self._get_organization(db_session, entity_id, includes)
            elif entity_type == "interaction":
                payload = self._get_interaction(db_session, entity_id)
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

    def _recent_interactions(
        self,
        db_session: Session,
        *,
        contact_id: UUID | None = None,
        organization_id: UUID | None = None,
    ) -> dict[str, Any]:
        interactions, total = list_interactions(
            db_session=db_session,
            page_num=0,
            page_size=RELATED_PAGE_SIZE,
            contact_id=contact_id,
            organization_id=organization_id,
        )
        return {
            "total": total,
            "items": serialize_interactions(db_session, interactions),
        }

    def _get_contact(
        self,
        db_session: Session,
        entity_id: UUID,
        includes: set[str],
    ) -> dict[str, Any]:
        contact = get_contact_by_id(entity_id, db_session)
        if contact is None:
            raise ToolCallException(
                message=f"Contact not found: {entity_id}",
                llm_facing_message="Could not find a contact with that ID.",
            )

        result: dict[str, Any] = {
            "status": "ok",
            "entity_type": "contact",
            "contact": serialize_contacts(db_session, [contact])[0],
        }

        if "organization" in includes and contact.organization_id:
            org = get_organization_by_id(contact.organization_id, db_session)
            if org:
                result["organization"] = serialize_organization(
                    org, tags=get_organization_tags(org.id, db_session)
                )

        if "interactions" in includes:
            result["recent_interactions"] = self._recent_interactions(
                db_session, contact_id=contact.id
            )

        return result

    def _get_organization(
        self,
        db_session: Session,
        entity_id: UUID,
        includes: set[str],
    ) -> dict[str, Any]:
        org = get_organization_by_id(entity_id, db_session)
        if org is None:
            raise ToolCallException(
                message=f"Organization not found: {entity_id}",
                llm_facing_message="Could not find an organization with that ID.",
            )

        result: dict[str, Any] = {
            "status": "ok",
            "entity_type": "organization",
            "organization": serialize_organization(
                org, tags=get_organization_tags(org.id, db_session)
            ),
        }

        if "contacts" in includes:
            contacts, total = list_contacts(
                db_session=db_session,
                page_num=0,
                page_size=RELATED_PAGE_SIZE,
                organization_id=org.id,
            )
            result["contacts"] = {
                "total": total,
                "items": serialize_contacts(db_session, contacts),
            }

        if "interactions" in includes:
            result["recent_interactions"] = self._recent_interactions(
                db_session, organization_id=org.id
            )

        return result

    def _get_interaction(self, db_session: Session, entity_id: UUID) -> dict[str, Any]:
        interaction = get_interaction_by_id(entity_id, db_session)
        if interaction is None:
            raise ToolCallException(
                message=f"Interaction not found: {entity_id}",
                llm_facing_message="Could not find an interaction with that ID.",
            )

        result: dict[str, Any] = {
            "status": "ok",
            "entity_type": "interaction",
            "interaction": serialize_interactions(db_session, [interaction])[0],
        }

        if interaction.contact_id:
            contact = get_contact_by_id(interaction.contact_id, db_session)
            if contact:
                result["contact"] = serialize_contacts(db_session, [contact])[0]

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
        entity_id: UUID,
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
