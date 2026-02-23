from __future__ import annotations

from typing import Any

from onyx.auth.users import get_anonymous_user
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.process_message import gather_stream_full
from onyx.chat.process_message import handle_stream_message_objects
from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()

CRM_PROMPT_TEMPLATE = """\
You are processing an inbound email on behalf of a CRM automation.
{internal_domains_block}
Perform the following steps using the available CRM tools:

1. Determine who the **external contact** is in this email:
   - If the sender is from an internal domain, this email is likely sharing \
information about an external person. Look at the email body, forwarded \
content, or signature blocks to identify the real external contact.
   - If the sender is NOT from an internal domain, they are the external contact.
2. Search the CRM for the external contact's email address.
3. If no matching contact is found, create a new contact with available \
information (name, email, phone, title, company).
4. Search the CRM for the external contact's organization (derive the org \
from their email domain or any signature details).
5. If no matching organization is found, create a new organization record.
6. Log this email as an interaction/activity on the contact record. Include \
relevant context from the email body.

IMPORTANT:
- Do NOT create or update contacts/organizations for internal domains. These \
are team members, not CRM leads.
- DO extract as much information as possible about external contacts from \
the email body (names, phone numbers, titles, company names).
- If the email contains no actionable external contact information, just log \
the interaction on any existing contact that is referenced.

Here is the email to process:

From: {from_field}
To: {to_field}
Subject: {subject}
Date: {date}

Body:
{body}

After completing all steps, reply with a short summary of what you did."""


def _get_internal_domains() -> list[str]:
    """Return the list of internal/team email domains from configuration."""
    from onyx.configs.app_configs import VALID_EMAIL_DOMAINS
    return VALID_EMAIL_DOMAINS


def _build_prompt(email_data: dict[str, Any]) -> str:
    """Build a structured CRM prompt from normalized email payload fields."""
    from_field = str(email_data.get("from") or "").strip()
    to_field = str(email_data.get("to") or "").strip()
    subject = str(
        email_data.get("subject") or email_data.get("semantic_identifier") or ""
    ).strip()
    date = str(email_data.get("date") or email_data.get("doc_updated_at") or "").strip()
    body = str(email_data.get("body") or email_data.get("text") or "").strip()

    if not from_field:
        primary_owner_emails = email_data.get("primary_owner_emails") or []
        if isinstance(primary_owner_emails, list) and primary_owner_emails:
            from_field = str(primary_owner_emails[0]).strip()

    if not to_field:
        secondary_owner_emails = email_data.get("secondary_owner_emails") or []
        if isinstance(secondary_owner_emails, list):
            to_field = ", ".join(
                str(email).strip()
                for email in secondary_owner_emails
                if str(email).strip()
            )

    # Extract a bare email address for the CRM lookup.  The ``from`` field
    # may be formatted as ``"Display Name <user@example.com>"``.
    sender_email = from_field
    if "<" in sender_email and ">" in sender_email:
        sender_email = sender_email.split("<", 1)[1].split(">", 1)[0]

    # Build the internal domains instruction block
    internal_domains = _get_internal_domains()
    if internal_domains:
        domains_str = ", ".join(f"@{d}" for d in internal_domains)
        internal_domains_block = (
            f"INTERNAL TEAM DOMAINS: {domains_str}\n"
            "Emails from these domains are from your own team members. "
            "Do NOT create or update CRM contacts/organizations for them. "
            "Instead, focus on any external contacts mentioned in the email."
        )
    else:
        internal_domains_block = ""

    return CRM_PROMPT_TEMPLATE.format(
        internal_domains_block=internal_domains_block,
        sender_email=sender_email,
        from_field=from_field,
        to_field=to_field,
        subject=subject,
        date=date,
        body=body,
    )


def _summarize_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return a lightweight list of tool-call summaries for the step output."""
    summaries: list[dict[str, str]] = []
    for tc in tool_calls:
        summaries.append(
            {
                "tool_name": tc.get("tool_name", "unknown"),
                "tool_result_preview": str(tc.get("tool_result", ""))[:500],
            }
        )
    return summaries


class ProcessEmailCrmStep(BaseStep):
    step_key = "process_email_crm"

    def run(self, context: StepContext) -> StepResult:
        # ------------------------------------------------------------------
        # 1. Validate configuration
        # ------------------------------------------------------------------
        persona_id = context.step_config.get("persona_id")
        if persona_id is None:
            return StepResult.failure(
                "persona_id is not configured in step_config. "
                "A CRM-focused persona must be specified."
            )

        try:
            persona_id = int(persona_id)
        except (TypeError, ValueError):
            return StepResult.failure(
                f"persona_id must be an integer, got: {persona_id!r}"
            )

        # ------------------------------------------------------------------
        # 2. Retrieve normalized email payload from the previous step
        # ------------------------------------------------------------------
        input_step_id = context.step_config.get(
            "input_step_id", "fetch_email_trigger_payload"
        )
        email_data = context.previous_outputs.get(input_step_id)
        if email_data is None:
            return StepResult.failure(
                f"Missing required step output: {input_step_id}"
            )

        # ------------------------------------------------------------------
        # 3. Build the user message prompt
        # ------------------------------------------------------------------
        prompt = _build_prompt(email_data)

        # ------------------------------------------------------------------
        # 4. Build the SendMessageRequest (mirrors Slack bot pattern)
        # ------------------------------------------------------------------
        # `stream` is not set here because it has no effect when calling
        # handle_stream_message_objects() directly (only the HTTP router
        # in chat_backend.py inspects it).
        new_message_request = SendMessageRequest(
            message=prompt,
            allowed_tool_ids=None,
            forced_tool_id=None,
            file_descriptors=[],
            deep_research=False,
            origin=MessageOrigin.API,
            chat_session_info=ChatSessionCreationRequest(
                persona_id=persona_id,
            ),
        )

        # ------------------------------------------------------------------
        # 5. Send through the chat pipeline (headless, like the Slack bot)
        # ------------------------------------------------------------------
        user = get_anonymous_user()
        state_container = ChatStateContainer()

        try:
            # Background automation has no real user context; bypass ACL so the
            # CRM persona and its tools are accessible without user-level
            # permissions.
            packets = handle_stream_message_objects(
                new_msg_req=new_message_request,
                user=user,
                db_session=context.db_session,
                bypass_acl=True,
                external_state_container=state_container,
            )
            response = gather_stream_full(packets, state_container)
        except Exception as e:
            logger.exception("ProcessEmailCrmStep: chat pipeline error")
            return StepResult.failure(
                f"Chat pipeline raised an exception: {e}"
            )

        # ------------------------------------------------------------------
        # 6. Check for errors in the response
        # ------------------------------------------------------------------
        if response.error_msg:
            return StepResult.failure(
                f"Chat pipeline returned an error: {response.error_msg}"
            )

        # ------------------------------------------------------------------
        # 7. Build summary output including tool call details
        # ------------------------------------------------------------------
        tool_call_dicts = [
            {
                "tool_name": tc.tool_name,
                "tool_arguments": tc.tool_arguments,
                "tool_result": tc.tool_result,
            }
            for tc in response.tool_calls
        ]

        return StepResult.success(
            output_json={
                "answer": response.answer,
                "tool_calls": _summarize_tool_calls(tool_call_dicts),
                "tool_call_count": len(response.tool_calls),
                "chat_session_id": (
                    str(response.chat_session_id)
                    if response.chat_session_id
                    else None
                ),
                "message_id": response.message_id,
            }
        )
