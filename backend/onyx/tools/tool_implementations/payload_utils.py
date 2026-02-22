from __future__ import annotations

import json
from typing import Any


MAX_COMPACT_STRING_LENGTH = 1200
MAX_COMPACT_ARRAY_ITEMS = 25
MAX_COMPACT_OBJECT_KEYS = 40
TRUNCATION_MARKER_PREFIX = "...[truncated"


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
    compacted = (
        payload if already_compacted else compact_tool_payload_for_model(payload)
    )
    return json.dumps(compacted, default=str)
