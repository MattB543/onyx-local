from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import list_contacts
from onyx.db.crm import list_interactions
from onyx.db.crm import list_organizations
from onyx.db.crm import list_tags
from onyx.db.crm import get_contact_tags
from onyx.db.crm import get_organization_tags
from onyx.db.enums import CrmContactStatus
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CrmListToolDelta
from onyx.server.query_and_chat.streaming_models import CrmListToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.crm.models import as_llm_json
from onyx.tools.tool_implementations.crm.models import compact_tool_payload_for_model
from onyx.tools.tool_implementations.crm.models import is_crm_schema_available
from onyx.tools.tool_implementations.crm.models import parse_enum_maybe
from onyx.tools.tool_implementations.crm.models import parse_uuid_maybe
from onyx.tools.tool_implementations.crm.models import serialize_contact
from onyx.tools.tool_implementations.crm.models import serialize_interaction
from onyx.tools.tool_implementations.crm.models import serialize_organization
from onyx.tools.tool_implementations.crm.models import serialize_tag


CRM_LIST_ENTITY_TYPES = {"contact", "organization", "interaction", "tag"}


class CrmListTool(Tool[None]):
    NAME = "crm_list"
    DISPLAY_NAME = "CRM List"
    DESCRIPTION = (
        "List and filter CRM records without a text query. Use this to browse contacts by status "
        "(e.g. all leads, all active), list contacts at a specific organization, list recent "
        "interactions for a contact or org, or list all tags. Supports pagination. "
        "For text-based searching by name or keyword, use crm_search instead."
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
                            "enum": sorted(list(CRM_LIST_ENTITY_TYPES)),
                            "description": "Which CRM entity type to list.",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["lead", "active", "inactive", "archived"],
                            "description": (
                                "Filter contacts by status. Only applies when entity_type is 'contact'."
                            ),
                        },
                        "organization_id": {
                            "type": "string",
                            "description": (
                                "Filter contacts by organization UUID. "
                                "Only applies when entity_type is 'contact'."
                            ),
                        },
                        "contact_id": {
                            "type": "string",
                            "description": (
                                "Filter interactions by contact UUID. "
                                "Only applies when entity_type is 'interaction'."
                            ),
                        },
                        "tag_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Filter contacts or organizations that have ALL of these tag UUIDs. "
                                "Only applies when entity_type is 'contact' or 'organization'."
                            ),
                        },
                        "page_num": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Page number (0-indexed). Defaults to 0.",
                        },
                        "page_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "description": "Number of results per page. Defaults to 25, max 50.",
                        },
                    },
                    "required": ["entity_type"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmListToolStart()))

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
        if entity_type not in CRM_LIST_ENTITY_TYPES:
            raise ToolCallException(
                message=f"Unsupported entity_type in {self.name}: {entity_type}",
                llm_facing_message="'entity_type' must be one of: contact, organization, interaction, tag.",
            )

        page_num_raw = llm_kwargs.get("page_num", 0)
        page_size_raw = llm_kwargs.get("page_size", 25)
        try:
            page_num = max(0, int(page_num_raw))
            page_size = min(50, max(1, int(page_size_raw)))
        except (TypeError, ValueError):
            raise ToolCallException(
                message=f"Invalid page_num/page_size in {self.name}",
                llm_facing_message="'page_num' and 'page_size' must be integers.",
            )

        with self._session_factory() as db_session:
            if entity_type == "contact":
                payload = self._list_contacts(db_session, llm_kwargs, page_num, page_size)
            elif entity_type == "organization":
                payload = self._list_organizations(db_session, llm_kwargs, page_num, page_size)
            elif entity_type == "interaction":
                payload = self._list_interactions(db_session, llm_kwargs, page_num, page_size)
            else:
                payload = self._list_tags(db_session, llm_kwargs, page_num, page_size)

        compact_payload = compact_tool_payload_for_model(payload)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CrmListToolDelta(payload=compact_payload),
            )
        )

        rich_response = json.dumps(payload, default=str)
        llm_response = as_llm_json(compact_payload, already_compacted=True)
        return ToolResponse(
            rich_response=rich_response,
            llm_facing_response=llm_response,
        )

    def _list_contacts(
        self,
        db_session: Session,
        llm_kwargs: dict[str, Any],
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        status = parse_enum_maybe(
            CrmContactStatus,
            llm_kwargs.get("status"),
            "status",
        ) if llm_kwargs.get("status") is not None else None

        organization_id = parse_uuid_maybe(
            llm_kwargs.get("organization_id"), "organization_id"
        )

        tag_ids_raw = llm_kwargs.get("tag_ids")
        tag_ids = None
        if tag_ids_raw and isinstance(tag_ids_raw, list):
            tag_ids = [
                parsed
                for raw in tag_ids_raw
                if (parsed := parse_uuid_maybe(raw, "tag_ids[]")) is not None
            ]
            if not tag_ids:
                tag_ids = None

        contacts, total = list_contacts(
            db_session=db_session,
            page_num=page_num,
            page_size=page_size,
            status=status,
            organization_id=organization_id,
            tag_ids=tag_ids,
        )

        return {
            "status": "ok",
            "entity_type": "contact",
            "page_num": page_num,
            "page_size": page_size,
            "total_items": total,
            "results": [
                serialize_contact(c, tags=get_contact_tags(c.id, db_session))
                for c in contacts
            ],
        }

    def _list_organizations(
        self,
        db_session: Session,
        llm_kwargs: dict[str, Any],
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        tag_ids_raw = llm_kwargs.get("tag_ids")
        tag_ids = None
        if tag_ids_raw and isinstance(tag_ids_raw, list):
            tag_ids = [
                parsed
                for raw in tag_ids_raw
                if (parsed := parse_uuid_maybe(raw, "tag_ids[]")) is not None
            ]
            if not tag_ids:
                tag_ids = None

        organizations, total = list_organizations(
            db_session=db_session,
            page_num=page_num,
            page_size=page_size,
            tag_ids=tag_ids,
        )

        return {
            "status": "ok",
            "entity_type": "organization",
            "page_num": page_num,
            "page_size": page_size,
            "total_items": total,
            "results": [
                serialize_organization(o, tags=get_organization_tags(o.id, db_session))
                for o in organizations
            ],
        }

    def _list_interactions(
        self,
        db_session: Session,
        llm_kwargs: dict[str, Any],
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        contact_id = parse_uuid_maybe(llm_kwargs.get("contact_id"), "contact_id")
        organization_id = parse_uuid_maybe(
            llm_kwargs.get("organization_id"), "organization_id"
        )

        interactions, total = list_interactions(
            db_session=db_session,
            page_num=page_num,
            page_size=page_size,
            contact_id=contact_id,
            organization_id=organization_id,
        )

        from onyx.db.crm import get_interaction_attendees

        return {
            "status": "ok",
            "entity_type": "interaction",
            "page_num": page_num,
            "page_size": page_size,
            "total_items": total,
            "results": [
                serialize_interaction(
                    i, attendees=get_interaction_attendees(i.id, db_session)
                )
                for i in interactions
            ],
        }

    def _list_tags(
        self,
        db_session: Session,
        llm_kwargs: dict[str, Any],  # noqa: ARG002
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        tags, total = list_tags(
            db_session=db_session,
            page_num=page_num,
            page_size=page_size,
        )

        return {
            "status": "ok",
            "entity_type": "tag",
            "page_num": page_num,
            "page_size": page_size,
            "total_items": total,
            "results": [serialize_tag(t) for t in tags],
        }
