from __future__ import annotations

from prometheus_client import Counter
from prometheus_client import Histogram

CUSTOM_JOB_RUNS_TOTAL = Counter(
    "custom_job_runs_total",
    "Total number of custom job runs by terminal status.",
    ["status", "workflow_key"],
)

CUSTOM_JOB_RUN_DURATION_SECONDS = Histogram(
    "custom_job_run_duration_seconds",
    "Custom job run duration in seconds.",
    ["workflow_key", "status"],
)

CUSTOM_JOB_STEP_FAILURES_TOTAL = Counter(
    "custom_job_step_failures_total",
    "Total number of custom job step failures.",
    ["step_key", "workflow_key"],
)

CUSTOM_JOB_EXTERNAL_API_ERRORS_TOTAL = Counter(
    "custom_job_external_api_errors_total",
    "Total number of custom job external API errors.",
    ["step_key", "api"],
)

_STEP_KEY_TO_EXTERNAL_API = {
    "post_slack_digest": "slack",
    "slack_channel_input": "slack",
    "web_search": "web_search",
    "google_doc_output": "google",
    "summarize_weekly_content": "llm",
}


def record_run_terminal(*, status: str, workflow_key: str) -> None:
    CUSTOM_JOB_RUNS_TOTAL.labels(status=status, workflow_key=workflow_key).inc()


def record_run_duration(*, duration_seconds: float, workflow_key: str, status: str) -> None:
    CUSTOM_JOB_RUN_DURATION_SECONDS.labels(
        workflow_key=workflow_key, status=status
    ).observe(max(duration_seconds, 0.0))


def record_step_failure(*, step_key: str, workflow_key: str) -> None:
    CUSTOM_JOB_STEP_FAILURES_TOTAL.labels(
        step_key=step_key, workflow_key=workflow_key
    ).inc()


def record_external_api_error(*, step_key: str) -> None:
    api = _STEP_KEY_TO_EXTERNAL_API.get(step_key)
    if api is None:
        return
    CUSTOM_JOB_EXTERNAL_API_ERRORS_TOTAL.labels(step_key=step_key, api=api).inc()
