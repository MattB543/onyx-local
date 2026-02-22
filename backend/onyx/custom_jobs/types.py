from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.db.enums import CustomJobStepStatus


class WorkflowStepDefinition(BaseModel):
    step_id: str
    step_key: str
    config: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class WorkflowDefinition(BaseModel):
    workflow_key: str
    steps: list[WorkflowStepDefinition]

    model_config = ConfigDict(extra="forbid")


@dataclass
class StepContext:
    db_session: Session
    tenant_id: str
    run_id: UUID
    job_id: UUID
    job_config: dict[str, Any]
    step_config: dict[str, Any]
    previous_outputs: dict[str, dict[str, Any]]
    deadline_monotonic: float


class StepResult(BaseModel):
    status: CustomJobStepStatus
    output_json: dict[str, Any] | None = None
    error_message: str | None = None

    @classmethod
    def success(cls, output_json: dict[str, Any] | None = None) -> "StepResult":
        return cls(status=CustomJobStepStatus.SUCCESS, output_json=output_json)

    @classmethod
    def skipped(
        cls, output_json: dict[str, Any] | None = None, reason: str | None = None
    ) -> "StepResult":
        return cls(
            status=CustomJobStepStatus.SKIPPED,
            output_json=output_json,
            error_message=reason,
        )

    @classmethod
    def failure(cls, error_message: str) -> "StepResult":
        return cls(status=CustomJobStepStatus.FAILURE, error_message=error_message)

    @classmethod
    def timeout(cls, error_message: str) -> "StepResult":
        return cls(status=CustomJobStepStatus.TIMEOUT, error_message=error_message)


class BaseStep(abc.ABC):
    step_key: str

    @abc.abstractmethod
    def run(self, context: StepContext) -> StepResult:
        raise NotImplementedError

