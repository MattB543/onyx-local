from __future__ import annotations

from typing import Any

from onyx.custom_jobs.types import WorkflowDefinition
from onyx.custom_jobs.types import WorkflowStepDefinition

EMAIL_CRM_PROCESSOR_WORKFLOW_KEY = "email_crm_processor"


def build_email_crm_processor_workflow(
    *, job_config: dict[str, Any]
) -> WorkflowDefinition:
    step_configs = job_config.get("step_configs", {})

    return WorkflowDefinition(
        workflow_key=EMAIL_CRM_PROCESSOR_WORKFLOW_KEY,
        steps=[
            WorkflowStepDefinition(
                step_id="fetch_email_trigger_payload",
                step_key="fetch_email_trigger_payload",
                config=step_configs.get("fetch_email_trigger_payload", {}),
                depends_on=[],
            ),
            WorkflowStepDefinition(
                step_id="process_email_crm",
                step_key="process_email_crm",
                config=step_configs.get("process_email_crm", {}),
                depends_on=["fetch_email_trigger_payload"],
            ),
        ],
    )
