from __future__ import annotations

from typing import Any

from onyx.custom_jobs.types import WorkflowDefinition
from onyx.custom_jobs.types import WorkflowStepDefinition

DAILY_SLACK_WEB_DRIVE_BRIEF_WORKFLOW_KEY = "daily_slack_web_drive_brief"


def build_daily_slack_web_drive_brief_workflow(
    *, job_config: dict[str, Any]
) -> WorkflowDefinition:
    step_configs = job_config.get("step_configs", {})

    return WorkflowDefinition(
        workflow_key=DAILY_SLACK_WEB_DRIVE_BRIEF_WORKFLOW_KEY,
        steps=[
            WorkflowStepDefinition(
                step_id="slack_channel_input",
                step_key="slack_channel_input",
                config=step_configs.get("slack_channel_input", {}),
                depends_on=[],
            ),
            WorkflowStepDefinition(
                step_id="web_search",
                step_key="web_search",
                config=step_configs.get("web_search", {}),
                depends_on=["slack_channel_input"],
            ),
            WorkflowStepDefinition(
                step_id="summarize_weekly_content",
                step_key="summarize_weekly_content",
                config=step_configs.get("summarize_weekly_content", {}),
                depends_on=["web_search"],
            ),
            WorkflowStepDefinition(
                step_id="google_doc_output",
                step_key="google_doc_output",
                config=step_configs.get("google_doc_output", {}),
                depends_on=["summarize_weekly_content"],
            ),
        ],
    )

