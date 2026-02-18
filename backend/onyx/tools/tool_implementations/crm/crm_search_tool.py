from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import search_crm_entities
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CrmSearchToolDelta
from onyx.server.query_and_chat.streaming_models import CrmSearchToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.crm.models import as_llm_json
from onyx.tools.tool_implementations.crm.models import compact_tool_payload_for_model
from onyx.tools.tool_implementations.crm.models import is_crm_schema_available


CRM_SEARCH_ENTITY_TYPES = {"contact", "organization", "interaction", "tag"}


class CrmSearchTool(Tool[None]):
    NAME = "crm_search"
    DISPLAY_NAME = "CRM Search"
    DESCRIPTION = (
        "Search CRM records by text query. Use this to find contacts by name or email, "
        "organizations by name, interactions by title or summary, or tags by name. "
        "Always search before creating to avoid duplicates. Use entity_types to narrow "
        "results (e.g. only contacts). Results are ranked by relevance. "
        "For structured filtering (by status, org, tags) without a text query, use crm_list instead."
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
                                "enum": sorted(list(CRM_SEARCH_ENTITY_TYPES)),
                            },
                            "description": "Entity types to search.",
                        },
                        "page_num": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Page number (0-indexed).",
                        },
                        "page_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "description": "Page size.",
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
            entity_types = []
            for value in entity_types_raw:
                if not isinstance(value, str):
                    continue
                lowered = value.strip().lower()
                if lowered in CRM_SEARCH_ENTITY_TYPES:
                    entity_types.append(lowered)
            if not entity_types:
                entity_types = None

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
            search_results, total_items = search_crm_entities(
                db_session=db_session,
                query=query,
                entity_types=entity_types,
                page_num=page_num,
                page_size=page_size,
            )

        payload = {
            "status": "ok",
            "query": query,
            "entity_types": entity_types or sorted(list(CRM_SEARCH_ENTITY_TYPES)),
            "page_num": page_num,
            "page_size": page_size,
            "total_items": total_items,
            "results": [
                {
                    "entity_type": result.entity_type,
                    "entity_id": result.entity_id,
                    "primary_text": result.primary_text,
                    "secondary_text": result.secondary_text,
                    "rank": result.rank,
                    "sort_at": result.sort_at.isoformat() if result.sort_at else None,
                }
                for result in search_results
            ],
        }

        compact_payload = compact_tool_payload_for_model(payload)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CrmSearchToolDelta(payload=compact_payload),
            )
        )

        rich_response = json.dumps(payload, default=str)
        llm_response = as_llm_json(compact_payload, already_compacted=True)
        return ToolResponse(
            rich_response=rich_response,
            llm_facing_response=llm_response,
        )
