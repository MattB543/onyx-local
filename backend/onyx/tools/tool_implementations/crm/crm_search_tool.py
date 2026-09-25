from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import (
    CrmContactAffiliation,
    CrmSearchResult,
    get_contact_affiliations,
    search_crm_entities,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CrmSearchToolDelta,
    CrmSearchToolStart,
    Packet,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException, ToolResponse
from onyx.tools.tool_implementations.crm.models import (
    REFER_BY_NAME_NOTE,
    crm_tool_response,
    is_crm_schema_available,
)
from onyx.tools.tool_implementations.crm.validation import (
    MAX_PAGE_SIZE,
    parse_page,
    reject_unknown_keys,
)
from onyx.tools.tool_implementations.error_delta import stream_tool_call_error

CRM_SEARCH_ENTITY_TYPES = {"contact", "organization", "interaction", "tag"}


def _affiliation_fields(affiliation: CrmContactAffiliation | None) -> dict[str, str]:
    """The affiliation fields that have a value."""
    if affiliation is None:
        return {}
    fields = {
        "title": affiliation.title,
        "organization_name": affiliation.organization_name,
        "principal": affiliation.principal,
        "principal_contact_id": (
            str(affiliation.principal_contact_id)
            if affiliation.principal_contact_id
            else None
        ),
        "principal_contact_name": affiliation.principal_contact_name,
    }
    return {key: value for key, value in fields.items() if value and value.strip()}


def _serialize_result(
    result: CrmSearchResult, affiliations: dict[UUID, CrmContactAffiliation]
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "entity_type": result.entity_type,
        "entity_id": result.entity_id,
        "primary_text": result.primary_text,
        "secondary_text": result.secondary_text,
        "sort_at": result.sort_at.isoformat() if result.sort_at else None,
    }
    if result.entity_type == "contact":
        item.update(_affiliation_fields(affiliations.get(UUID(result.entity_id))))
    return item


class CrmSearchTool(Tool[None]):
    NAME = "crm_search"
    DISPLAY_NAME = "CRM Search"
    DESCRIPTION = (
        "Keyword search across CRM contacts, organizations, interactions, and tags. "
        "Search before creating to avoid duplicates. To filter by status, tag, org, "
        "or date, use crm_list. Contacts include title, organization and principal "
        "(the official a staffer works for; principal_contact_id and "
        "principal_contact_name identify the official's contact when linked). To "
        "list an official's staff, use crm_list entity_type='contact' "
        "principal=<name>, or crm_get on the official's contact with "
        "include=['staff']. " + REFER_BY_NAME_NOTE
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
                        "query": {
                            "type": "string",
                            "description": "Text query to search in CRM records.",
                        },
                        "entity_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": sorted(CRM_SEARCH_ENTITY_TYPES),
                            },
                            "description": "Entity types to search. Default: all.",
                        },
                        "page_num": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Page number (0-indexed).",
                        },
                        "page_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_PAGE_SIZE,
                            "description": f"Default and max {MAX_PAGE_SIZE}.",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmSearchToolStart()))

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        with stream_tool_call_error(self.emitter, placement, CrmSearchToolDelta):
            return self._run(placement, llm_kwargs)

    def _run(self, placement: Placement, llm_kwargs: dict[str, Any]) -> ToolResponse:
        reject_unknown_keys(
            llm_kwargs,
            ("query", "entity_types", "page_num", "page_size"),
            "crm_search arguments",
        )
        query = llm_kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolCallException(
                message=f"Missing/invalid query in {self.name} tool call",
                llm_facing_message="'query' must be a non-empty string.",
            )

        entity_types_raw = llm_kwargs.get("entity_types")
        entity_types: list[str] | None = None
        if entity_types_raw is not None:
            if not isinstance(entity_types_raw, list):
                raise ToolCallException(
                    message=f"Invalid entity_types in {self.name}: {entity_types_raw}",
                    llm_facing_message="'entity_types' must be a list of strings.",
                )
            normalized: list[Any] = [
                value.strip().lower() if isinstance(value, str) else value
                for value in entity_types_raw
            ]
            invalid = [
                json.dumps(value, default=str)
                for value in normalized
                if not isinstance(value, str) or value not in CRM_SEARCH_ENTITY_TYPES
            ]
            if invalid:
                raise ToolCallException(
                    message=f"Invalid entity_types in {self.name}: {invalid}",
                    llm_facing_message=(
                        f"Invalid 'entity_types' value(s): {', '.join(invalid)}. "
                        f"Allowed: {', '.join(sorted(CRM_SEARCH_ENTITY_TYPES))}; "
                        "omit to search all."
                    ),
                )
            entity_types = list(dict.fromkeys(str(v) for v in normalized)) or None

        page_num, page_size = parse_page(llm_kwargs, self.name)

        with self._session_factory() as db_session:
            search_results, total_items = search_crm_entities(
                db_session=db_session,
                query=query,
                entity_types=entity_types,
                page_num=page_num,
                page_size=page_size,
            )
            affiliations = get_contact_affiliations(
                {
                    UUID(result.entity_id)
                    for result in search_results
                    if result.entity_type == "contact"
                },
                db_session,
            )

        payload = {
            "status": "ok",
            "query": query,
            "entity_types": entity_types or sorted(CRM_SEARCH_ENTITY_TYPES),
            "page_num": page_num,
            "page_size": page_size,
            "total_items": total_items,
            "results": [
                _serialize_result(result, affiliations) for result in search_results
            ],
        }

        return crm_tool_response(self.emitter, placement, payload, CrmSearchToolDelta)
