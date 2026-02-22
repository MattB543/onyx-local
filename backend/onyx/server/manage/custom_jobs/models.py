from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.db.enums import CustomJobRunStatus
from onyx.db.enums import CustomJobStepStatus
from onyx.db.enums import CustomJobTriggerType
from onyx.db.models import CustomJob
from onyx.db.models import CustomJobRun
from onyx.db.models import CustomJobRunStep


class CustomJobView(BaseModel):
    id: UUID
    name: str
    workflow_key: str
    enabled: bool
    trigger_type: CustomJobTriggerType
    day_of_week: int | None
    hour: int | None
    minute: int | None
    timezone: str | None
    next_run_at: datetime | None
    last_scheduled_at: datetime | None
    trigger_source_type: str | None
    trigger_source_config: dict[str, Any] | None
    job_config: dict[str, Any]
    persona_id: int | None
    slack_bot_id: int | None
    slack_channel_id: str | None
    retention_days: int
    created_by: UUID | None
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, model: CustomJob) -> "CustomJobView":
        return cls(
            id=model.id,
            name=model.name,
            workflow_key=model.workflow_key,
            enabled=model.enabled,
            trigger_type=model.trigger_type,
            day_of_week=model.day_of_week,
            hour=model.hour,
            minute=model.minute,
            timezone=model.timezone,
            next_run_at=model.next_run_at,
            last_scheduled_at=model.last_scheduled_at,
            trigger_source_type=model.trigger_source_type,
            trigger_source_config=model.trigger_source_config,
            job_config=model.job_config or {},
            persona_id=model.persona_id,
            slack_bot_id=model.slack_bot_id,
            slack_channel_id=model.slack_channel_id,
            retention_days=model.retention_days,
            created_by=model.created_by,
            updated_by=model.updated_by,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class CustomJobCreateRequest(BaseModel):
    name: str
    workflow_key: str
    enabled: bool = True
    trigger_type: CustomJobTriggerType
    day_of_week: int | None = None
    hour: int | None = None
    minute: int | None = None
    timezone: str | None = None
    trigger_source_type: str | None = None
    trigger_source_config: dict[str, Any] | None = None
    job_config: dict[str, Any] = Field(default_factory=dict)
    persona_id: int | None = None
    slack_bot_id: int | None = None
    slack_channel_id: str | None = None
    retention_days: int = Field(default=90, ge=1, le=3650)


class CustomJobUpdateRequest(BaseModel):
    name: str | None = None
    workflow_key: str | None = None
    enabled: bool | None = None
    trigger_type: CustomJobTriggerType | None = None
    day_of_week: int | None = None
    hour: int | None = None
    minute: int | None = None
    timezone: str | None = None
    trigger_source_type: str | None = None
    trigger_source_config: dict[str, Any] | None = None
    job_config: dict[str, Any] | None = None
    persona_id: int | None = None
    slack_bot_id: int | None = None
    slack_channel_id: str | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class CustomJobRunView(BaseModel):
    id: UUID
    custom_job_id: UUID
    status: CustomJobRunStatus
    scheduled_for: datetime | None
    trigger_event_id: UUID | None
    idempotency_key: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    metrics_json: dict[str, Any] | None
    output_preview: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, model: CustomJobRun) -> "CustomJobRunView":
        return cls(
            id=model.id,
            custom_job_id=model.custom_job_id,
            status=model.status,
            scheduled_for=model.scheduled_for,
            trigger_event_id=model.trigger_event_id,
            idempotency_key=model.idempotency_key,
            started_at=model.started_at,
            finished_at=model.finished_at,
            error_message=model.error_message,
            metrics_json=model.metrics_json,
            output_preview=model.output_preview,
            created_at=model.created_at,
        )


class CustomJobRunStepView(BaseModel):
    id: UUID
    run_id: UUID
    step_index: int
    step_id: str
    step_key: str
    status: CustomJobStepStatus
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    output_json: dict[str, Any] | None

    @classmethod
    def from_model(cls, model: CustomJobRunStep) -> "CustomJobRunStepView":
        return cls(
            id=model.id,
            run_id=model.run_id,
            step_index=model.step_index,
            step_id=model.step_id,
            step_key=model.step_key,
            status=model.status,
            started_at=model.started_at,
            finished_at=model.finished_at,
            error_message=model.error_message,
            output_json=model.output_json,
        )


class PaginatedCustomJobRuns(BaseModel):
    items: list[CustomJobRunView]
    total_items: int


class PaginatedCustomJobRunSteps(BaseModel):
    items: list[CustomJobRunStepView]
    total_items: int


class CustomJobStepCatalogItem(BaseModel):
    step_key: str
    description: str
    config_schema: dict[str, Any]


class CustomJobManualTriggerResponse(BaseModel):
    run_id: UUID
    status: str


class CustomJobDryRunResponse(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    step_count: int
