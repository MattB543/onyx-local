from __future__ import annotations

from typing import Any
from typing import Callable

from onyx.custom_jobs.steps import STEP_CLASS_MAP
from onyx.custom_jobs.steps import STEP_DESCRIPTION_MAP
from onyx.custom_jobs.types import WorkflowDefinition
from onyx.custom_jobs.workflows import DAILY_SLACK_WEB_DRIVE_BRIEF_WORKFLOW_KEY
from onyx.custom_jobs.workflows import EMAIL_CRM_PROCESSOR_WORKFLOW_KEY
from onyx.custom_jobs.workflows import WEEKLY_CONTENT_SUMMARY_WORKFLOW_KEY
from onyx.custom_jobs.workflows import build_daily_slack_web_drive_brief_workflow
from onyx.custom_jobs.workflows import build_email_crm_processor_workflow
from onyx.custom_jobs.workflows import build_weekly_content_summary_workflow

WorkflowBuilder = Callable[..., WorkflowDefinition]

WORKFLOW_REGISTRY: dict[str, WorkflowBuilder] = {
    WEEKLY_CONTENT_SUMMARY_WORKFLOW_KEY: build_weekly_content_summary_workflow,
    DAILY_SLACK_WEB_DRIVE_BRIEF_WORKFLOW_KEY: build_daily_slack_web_drive_brief_workflow,
    EMAIL_CRM_PROCESSOR_WORKFLOW_KEY: build_email_crm_processor_workflow,
}

STEP_CONFIG_SCHEMAS: dict[str, dict[str, Any]] = {
    "fetch_weekly_chat_content": {
        "type": "object",
        "properties": {
            "window_days": {"type": "integer", "minimum": 1},
            "max_messages": {"type": "integer", "minimum": 1},
            "min_messages": {"type": "integer", "minimum": 1},
        },
    },
    "summarize_weekly_content": {
        "type": "object",
        "properties": {
            "input_step_id": {"type": "string"},
            "min_messages": {"type": "integer", "minimum": 1},
            "max_chunks": {"type": "integer", "minimum": 1},
        },
    },
    "post_slack_digest": {
        "type": "object",
        "properties": {
            "input_step_id": {"type": "string"},
            "slack_bot_id": {"type": "integer"},
            "channel_id": {"type": "string"},
        },
    },
    "slack_channel_input": {
        "type": "object",
        "properties": {
            "slack_bot_id": {"type": "integer"},
            "channel_ids": {"type": "array", "items": {"type": "string"}},
            "oldest": {"type": "string"},
            "latest": {"type": "string"},
            "max_messages_per_channel": {"type": "integer", "minimum": 1},
        },
    },
    "web_search": {
        "type": "object",
        "properties": {
            "queries": {"type": "array", "items": {"type": "string"}},
            "max_results": {"type": "integer", "minimum": 1},
            "cache_ttl_seconds": {"type": "integer", "minimum": 0},
            "max_cache_entries": {"type": "integer", "minimum": 1},
        },
    },
    "google_doc_output": {
        "type": "object",
        "properties": {
            "input_step_id": {"type": "string"},
            "credential_id": {"type": "integer"},
            "title": {"type": "string"},
            "folder_id": {"type": "string"},
            "share_with": {"type": "array", "items": {"type": "string"}},
        },
    },
    "fetch_email_trigger_payload": {
        "type": "object",
        "properties": {},
    },
    "process_email_crm": {
        "type": "object",
        "properties": {
            "persona_id": {"type": "integer"},
            "input_step_id": {"type": "string"},
        },
    },
}


def build_workflow_definition(
    *,
    workflow_key: str,
    job_config: dict[str, Any],
) -> WorkflowDefinition:
    builder = WORKFLOW_REGISTRY.get(workflow_key)
    if builder is None:
        raise ValueError(f"Unknown workflow key: {workflow_key}")
    return builder(job_config=job_config)


def get_step_class(step_key: str) -> type:
    step_cls = STEP_CLASS_MAP.get(step_key)
    if step_cls is None:
        raise ValueError(f"Unknown step key: {step_key}")
    return step_cls


def get_step_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for step_key in sorted(STEP_CLASS_MAP.keys()):
        catalog.append(
            {
                "step_key": step_key,
                "description": STEP_DESCRIPTION_MAP.get(step_key, ""),
                "config_schema": STEP_CONFIG_SCHEMAS.get(step_key, {"type": "object"}),
            }
        )
    return catalog


def list_workflow_keys() -> list[str]:
    return sorted(WORKFLOW_REGISTRY.keys())
