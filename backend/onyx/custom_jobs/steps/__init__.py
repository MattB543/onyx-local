from onyx.custom_jobs.steps.fetch_email_trigger_payload import FetchEmailTriggerPayloadStep
from onyx.custom_jobs.steps.fetch_weekly_chat_content import FetchWeeklyChatContentStep
from onyx.custom_jobs.steps.google_doc_output import GoogleDocOutputStep
from onyx.custom_jobs.steps.post_slack_digest import PostSlackDigestStep
from onyx.custom_jobs.steps.process_email_crm import ProcessEmailCrmStep
from onyx.custom_jobs.steps.slack_channel_input import SlackChannelInputStep
from onyx.custom_jobs.steps.summarize_weekly_content import SummarizeWeeklyContentStep
from onyx.custom_jobs.steps.web_search_step import WebSearchStep

STEP_CLASS_MAP = {
    FetchEmailTriggerPayloadStep.step_key: FetchEmailTriggerPayloadStep,
    FetchWeeklyChatContentStep.step_key: FetchWeeklyChatContentStep,
    SummarizeWeeklyContentStep.step_key: SummarizeWeeklyContentStep,
    PostSlackDigestStep.step_key: PostSlackDigestStep,
    ProcessEmailCrmStep.step_key: ProcessEmailCrmStep,
    SlackChannelInputStep.step_key: SlackChannelInputStep,
    WebSearchStep.step_key: WebSearchStep,
    GoogleDocOutputStep.step_key: GoogleDocOutputStep,
}

STEP_DESCRIPTION_MAP = {
    "fetch_email_trigger_payload": "Reads and validates the email trigger event payload for downstream CRM processing.",
    "fetch_weekly_chat_content": "Fetches chat USER/ASSISTANT messages for a time window.",
    "summarize_weekly_content": "Generates a weekly summary with token-aware single-pass/map-reduce behavior.",
    "post_slack_digest": "Posts a markdown summary to Slack and threads long chunks.",
    "process_email_crm": "Sends an email through the chat pipeline with a CRM persona to search/create contacts, orgs, and log interactions.",
    "slack_channel_input": "Reads channel messages via Slack conversations.history.",
    "web_search": "Runs configured web queries with partial-failure tolerance.",
    "google_doc_output": "Creates a Google Doc and writes output content.",
}

