from __future__ import annotations

import time

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult
from onyx.db.slack_bot import fetch_slack_bot
from onyx.onyxbot.slack.formatting import format_slack_message


def _split_text(text: str, limit: int = 3000) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        split_at = remaining.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    return chunks


def _map_slack_error(error_code: str) -> str:
    mapped = {
        "not_in_channel": "Bot is not in target channel.",
        "channel_not_found": "Slack channel not found.",
        "is_archived": "Slack channel is archived.",
        "msg_too_long": "Slack message too long.",
        "rate_limited": "Slack rate limited request.",
        "token_revoked": "Slack bot token has been revoked.",
    }
    return mapped.get(error_code, f"Slack API error: {error_code}")


class PostSlackDigestStep(BaseStep):
    step_key = "post_slack_digest"

    def run(self, context: StepContext) -> StepResult:
        input_step_id = context.step_config.get("input_step_id", "summarize_weekly_content")
        input_payload = context.previous_outputs.get(input_step_id)
        if input_payload is None:
            return StepResult.failure(f"Missing required step output: {input_step_id}")

        summary = (input_payload.get("summary") or "").strip()
        if not summary:
            return StepResult.skipped(
                output_json={"posted": False, "reason": "empty_summary"},
                reason="No summary content to post.",
            )

        slack_bot_id = context.step_config.get("slack_bot_id") or context.job_config.get(
            "slack_bot_id"
        )
        channel_id = context.step_config.get("channel_id") or context.job_config.get(
            "slack_channel_id"
        )
        if not slack_bot_id or not channel_id:
            return StepResult.failure(
                "Missing slack_bot_id or channel_id in step/job configuration."
            )

        slack_bot = fetch_slack_bot(context.db_session, int(slack_bot_id))
        if slack_bot.bot_token is None:
            return StepResult.failure("Slack bot token is missing.")
        token = slack_bot.bot_token.get_value(apply_mask=False)
        if not token:
            return StepResult.failure("Slack bot token is empty.")

        markdown_text = format_slack_message(summary)
        chunks = _split_text(markdown_text, limit=3000)
        client = WebClient(token=token)

        try:
            first_resp = client.chat_postMessage(channel=channel_id, text=chunks[0])
            root_ts = first_resp["ts"]
            for chunk in chunks[1:]:
                # Slack recommends pacing per-channel posts.
                time.sleep(1)
                client.chat_postMessage(channel=channel_id, text=chunk, thread_ts=root_ts)
        except SlackApiError as e:
            error_code = str(e.response.get("error", "unknown_error"))
            return StepResult.failure(_map_slack_error(error_code))
        except Exception as e:
            return StepResult.failure(f"Failed to post Slack digest: {e}")

        return StepResult.success(
            output_json={
                "posted": True,
                "channel_id": channel_id,
                "thread_ts": root_ts,
                "chunk_count": len(chunks),
            }
        )

