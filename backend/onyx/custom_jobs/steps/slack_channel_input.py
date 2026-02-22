from __future__ import annotations

import time
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult
from onyx.db.slack_bot import fetch_slack_bot


class SlackChannelInputStep(BaseStep):
    step_key = "slack_channel_input"

    def run(self, context: StepContext) -> StepResult:
        slack_bot_id = context.step_config.get("slack_bot_id") or context.job_config.get(
            "slack_bot_id"
        )
        channel_ids = context.step_config.get("channel_ids") or []
        if not slack_bot_id or not channel_ids:
            return StepResult.failure(
                "Missing slack_bot_id or channel_ids for slack_channel_input step."
            )

        max_messages_per_channel = int(
            context.step_config.get("max_messages_per_channel", 200)
        )
        oldest = context.step_config.get("oldest")
        latest = context.step_config.get("latest")

        slack_bot = fetch_slack_bot(context.db_session, int(slack_bot_id))
        if slack_bot.bot_token is None:
            return StepResult.failure("Slack bot token is missing.")
        token = slack_bot.bot_token.get_value(apply_mask=False)
        if not token:
            return StepResult.failure("Slack bot token is empty.")

        client = WebClient(token=token)
        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for channel_id in channel_ids:
            try:
                response = client.conversations_history(
                    channel=channel_id,
                    oldest=oldest,
                    latest=latest,
                    limit=max_messages_per_channel,
                )
                for message in response.get("messages", []):
                    results.append(
                        {
                            "channel_id": channel_id,
                            "ts": message.get("ts"),
                            "user": message.get("user"),
                            "text": message.get("text", ""),
                        }
                    )
                time.sleep(1)
            except SlackApiError as e:
                error_code = str(e.response.get("error", "unknown_error"))
                errors.append({"channel_id": channel_id, "error": error_code})
                if error_code == "rate_limited":
                    retry_after = int(e.response.headers.get("Retry-After", "1"))
                    time.sleep(max(retry_after, 1))
                    continue
            except Exception as e:
                errors.append({"channel_id": channel_id, "error": str(e)})

        if not results and errors:
            return StepResult.failure(
                f"Slack channel input failed for all channels: {errors}"
            )

        return StepResult.success(
            output_json={
                "messages": results,
                "message_count": len(results),
                "errors": errors,
            }
        )

