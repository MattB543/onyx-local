from __future__ import annotations

from onyx.custom_jobs.registry import STEP_CONFIG_SCHEMAS
from onyx.custom_jobs.registry import WORKFLOW_REGISTRY
from onyx.custom_jobs.steps import STEP_CLASS_MAP
from onyx.custom_jobs.workflows.email_crm_processor import (
    EMAIL_CRM_PROCESSOR_WORKFLOW_KEY,
)
from onyx.custom_jobs.workflows.email_crm_processor import (
    build_email_crm_processor_workflow,
)


def test_build_email_crm_processor_workflow_structure() -> None:
    workflow = build_email_crm_processor_workflow(
        job_config={
            "step_configs": {
                "process_email_crm": {
                    "persona_id": 7,
                    "input_step_id": "fetch_email_trigger_payload",
                }
            }
        }
    )

    assert workflow.workflow_key == EMAIL_CRM_PROCESSOR_WORKFLOW_KEY
    assert len(workflow.steps) == 2
    assert workflow.steps[0].step_id == "fetch_email_trigger_payload"
    assert workflow.steps[0].depends_on == []
    assert workflow.steps[1].step_id == "process_email_crm"
    assert workflow.steps[1].depends_on == ["fetch_email_trigger_payload"]
    assert workflow.steps[1].config["persona_id"] == 7


def test_email_crm_workflow_and_steps_are_registered() -> None:
    assert EMAIL_CRM_PROCESSOR_WORKFLOW_KEY in WORKFLOW_REGISTRY
    assert "fetch_email_trigger_payload" in STEP_CLASS_MAP
    assert "process_email_crm" in STEP_CLASS_MAP
    assert "fetch_email_trigger_payload" in STEP_CONFIG_SCHEMAS
    assert "process_email_crm" in STEP_CONFIG_SCHEMAS
