from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.constants import MessageType
from onyx.configs.constants import QueryHistoryType
from onyx.db.chat import get_chat_messages_in_time_range
from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult


class FetchWeeklyChatContentStep(BaseStep):
    step_key = "fetch_weekly_chat_content"

    def run(self, context: StepContext) -> StepResult:
        if ONYX_QUERY_HISTORY_TYPE in {
            QueryHistoryType.DISABLED,
            QueryHistoryType.ANONYMIZED,
        }:
            return StepResult.skipped(
                output_json={
                    "message_count": 0,
                    "window_start": None,
                    "window_end": None,
                    "skip_reason": f"query_history_mode={ONYX_QUERY_HISTORY_TYPE.value}",
                },
                reason="Query history mode does not permit this job input in v1.",
            )

        now_utc = datetime.now(timezone.utc)
        window_days = int(context.step_config.get("window_days", 7))
        max_messages = int(context.step_config.get("max_messages", 5000))
        min_messages = int(context.step_config.get("min_messages", 1))

        window_end = now_utc
        window_start = now_utc - timedelta(days=max(window_days, 1))

        messages = get_chat_messages_in_time_range(
            db_session=context.db_session,
            window_start=window_start,
            window_end=window_end,
            message_types=[MessageType.USER, MessageType.ASSISTANT],
            limit=max_messages,
        )

        items: list[dict[str, Any]] = []
        for msg in messages:
            items.append(
                {
                    "chat_session_id": str(msg.chat_session_id),
                    "message_id": msg.id,
                    "message_type": msg.message_type.value,
                    "time_sent": msg.time_sent.isoformat(),
                    "message": msg.message,
                }
            )

        if len(items) < min_messages:
            return StepResult.skipped(
                output_json={
                    "message_count": len(items),
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "messages": items,
                },
                reason="Insufficient messages in window.",
            )

        return StepResult.success(
            output_json={
                "message_count": len(items),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "messages": items,
            }
        )

