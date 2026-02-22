from __future__ import annotations

from typing import Any

from onyx.custom_jobs.types import WorkflowDefinition
from onyx.custom_jobs.types import WorkflowStepDefinition

WEEKLY_CONTENT_SUMMARY_WORKFLOW_KEY = "weekly_content_summary_to_slack"


def build_weekly_content_summary_workflow(
    *, job_config: dict[str, Any]
) -> WorkflowDefinition:
    step_configs = job_config.get("step_configs", {})

    return WorkflowDefinition(
        workflow_key=WEEKLY_CONTENT_SUMMARY_WORKFLOW_KEY,
        steps=[
            WorkflowStepDefinition(
                step_id="fetch_weekly_chat_content",
                step_key="fetch_weekly_chat_content",
                config=step_configs.get("fetch_weekly_chat_content", {}),
                depends_on=[],
            ),
            WorkflowStepDefinition(
                step_id="summarize_weekly_content",
                step_key="summarize_weekly_content",
                config=step_configs.get("summarize_weekly_content", {}),
                depends_on=["fetch_weekly_chat_content"],
            ),
            WorkflowStepDefinition(
                step_id="post_slack_digest",
                step_key="post_slack_digest",
                config=step_configs.get("post_slack_digest", {}),
                depends_on=["summarize_weekly_content"],
            ),
        ],
    )

