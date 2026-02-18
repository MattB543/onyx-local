#!/usr/bin/env python3
"""Convert Claude session JSONL logs into a simple markdown conversation."""

from __future__ import annotations

import argparse
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKIP_SNIPPETS = (
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<command-name>",
    "<command-message>",
)


@dataclass
class Message:
    idx: int
    role: str
    timestamp: str
    content: str


def _clean_text(value: str) -> str:
    text = value.replace("\r\n", "\n").strip()
    return text


def _should_skip(content: str) -> bool:
    return any(marker in content for marker in SKIP_SNIPPETS)


def _serialize_block(block: dict[str, Any], include_thinking: bool, include_tool_use: bool) -> str:
    block_type = block.get("type")
    if block_type == "text":
        return _clean_text(str(block.get("text", "")))
    if block_type == "thinking":
        if not include_thinking:
            return ""
        return "[thinking]\n" + _clean_text(str(block.get("thinking", "")))
    if block_type == "tool_use":
        if not include_tool_use:
            return ""
        name = block.get("name", "tool")
        tool_input = block.get("input", {})
        return f"[tool_use] {name}\n```json\n{json.dumps(tool_input, indent=2, ensure_ascii=False)}\n```"
    if block_type == "tool_result":
        if not include_tool_use:
            return ""
        raw = block.get("content", "")
        if isinstance(raw, list):
            raw = "\n".join(
                str(part.get("text", part)) if isinstance(part, dict) else str(part)
                for part in raw
            )
        return "[tool_result]\n" + _clean_text(str(raw))
    return ""


def _normalize_content(
    content: Any,
    include_thinking: bool,
    include_tool_use: bool,
) -> str:
    if isinstance(content, str):
        return _clean_text(content)

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                item = _serialize_block(block, include_thinking, include_tool_use)
                if item:
                    parts.append(item)
            else:
                raw = _clean_text(str(block))
                if raw:
                    parts.append(raw)
        return "\n\n".join(parts).strip()

    if isinstance(content, dict):
        return _clean_text(json.dumps(content, indent=2, ensure_ascii=False))

    return _clean_text(str(content))


def _extract_top_level_message(
    obj: dict[str, Any],
    include_thinking: bool,
    include_tool_use: bool,
) -> tuple[str, str, str] | None:
    record_type = obj.get("type")
    if record_type not in {"user", "assistant"}:
        return None

    message = obj.get("message")
    if not isinstance(message, dict):
        return None

    role = str(message.get("role", record_type)).strip() or record_type
    content = _normalize_content(message.get("content", ""), include_thinking, include_tool_use)
    if not content:
        return None

    if _should_skip(content):
        return None

    timestamp = str(obj.get("timestamp", ""))
    return role, timestamp, content


def convert(
    input_path: Path,
    output_path: Path,
    include_thinking: bool,
    include_tool_use: bool,
) -> None:
    messages: list[Message] = []

    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            extracted = _extract_top_level_message(
                obj,
                include_thinking=include_thinking,
                include_tool_use=include_tool_use,
            )
            if not extracted:
                continue

            role, timestamp, content = extracted
            messages.append(
                Message(idx=len(messages) + 1, role=role, timestamp=timestamp, content=content)
            )

    header = [
        f"# Conversation ({input_path.name})",
        "",
        f"- Source: `{input_path}`",
        f"- Messages: {len(messages)}",
        "",
    ]

    chunks: list[str] = ["\n".join(header)]
    for msg in messages:
        title = f"## {msg.idx:03d} {msg.role.title()}"
        if msg.timestamp:
            title += f" ({msg.timestamp})"

        body = msg.content
        if "```" not in body:
            body = textwrap.dedent(body).strip()

        chunks.append(f"{title}\n\n{body}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(chunks), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Claude JSONL logs to markdown conversation."
    )
    parser.add_argument("input", type=Path, help="Path to JSONL session file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output markdown path (default: input with .md suffix)",
    )
    parser.add_argument(
        "--include-thinking",
        action="store_true",
        help="Include assistant thinking blocks",
    )
    parser.add_argument(
        "--include-tool-use",
        action="store_true",
        help="Include tool use/result blocks when present at top level",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path: Path = args.input
    output_path = args.output or input_path.with_suffix(".md")
    convert(
        input_path=input_path,
        output_path=output_path,
        include_thinking=args.include_thinking,
        include_tool_use=args.include_tool_use,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
