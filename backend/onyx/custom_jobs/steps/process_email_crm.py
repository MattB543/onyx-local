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
Your job is to keep the CRM accurate, complete, and free of duplicates based on
the entire email thread.

{internal_domains_block}

You may have access to the following CRM tools:
- `crm_search` for text search across contacts, organizations, interactions,
  and tags.
- `crm_list` for structured filtering, such as recent interactions for a
  contact or organization.
- `crm_get` for full details on an existing CRM record and its related history.
- `crm_create` for creating missing contacts, organizations, or tags.
- `crm_update` for enriching existing contacts or organizations with reliable
  new information.
- `crm_log_interaction` for logging this email thread as an activity.

Perform the following workflow using the available CRM tools:

1. Read the entire email carefully, including the body, quoted replies,
   forwarded content, signature blocks, and relationship clues.
2. Identify all relevant **external people and organizations** mentioned in the
   email. Do not limit yourself to the sender or recipients. The From/To fields
   are only starting points.
   - If the sender is from an internal domain, the real CRM-relevant contact may
     be someone mentioned in the body or forwarded content.
   - If the email thread mentions another external person by name, title,
     company, email, phone number, or relationship context, that person may
     also deserve a CRM contact even if they are not in the headers.
3. Determine the primary external contact and any additional external contacts
   or organizations that are materially relevant to the relationship.
4. For each relevant external contact, search the CRM first using the strongest
   identifiers available:
   - Prefer email when present.
   - Otherwise use combinations of name, company, and context clues.
   - Use `crm_get` or `crm_list` if you need full details or recent interaction
     history before deciding what to do.
5. If a relevant contact already exists, update it with reliable net-new
   information from the email when appropriate (for example: phone, title,
   organization, location, notes, or relationship context).
   - Do not overwrite strong existing data with weak guesses.
6. If no matching contact exists, create one with the best clearly supported
   information available.
7. Search for the relevant external organization(s). An abbreviation or short
   name alone may not match; try multiple search terms:
   - The full company name and any abbreviations or acronyms.
   - The email domain (e.g., search for "flf.org" if the contact's email is
     ben@flf.org).
   - The website if mentioned in the email.
   Use `crm_get` or `crm_list` if you need full details or context on a
   candidate match before deciding.
8. If a relevant organization already exists, update it with reliable net-new
   information from the email when appropriate. If it does not exist, create it.
9. Log this email as an interaction/activity. Use `interaction_type` "email"
   or "note" as appropriate, and set `occurred_at` to the email date so the
   interaction is recorded at the correct time. Include the key relationship
   context from the email body, any action items, and link it to the best
   matching contact and organization.
   - For attendees, only use `contact_id` values from contacts you have
     already found or created in the CRM. Do NOT pass raw email addresses or
     names as attendees — unresolvable attendees can block the interaction
     from being saved.

IMPORTANT:
- Do NOT create or update contacts/organizations for internal domains. These
  are team members, not CRM leads.
- Internal teammates may appear in the headers or body and can still be useful
  as context, but they should not become CRM contacts or organizations.
- DO extract as much information as possible about relevant external people and
  organizations from the email body (names, phone numbers, titles, company
  names, websites, locations, and relationship context).
- Mentioned external people can be valid CRM contacts even if they are not the
  sender or direct recipients.
- Always search before creating to avoid duplicates.
- If the email contains no actionable external CRM data, avoid creating new
  contacts or organizations and just log the interaction on any clearly
  referenced existing record.

Here is the email to process:

From: {from_field}
To: {to_field}
Subject: {subject}
Date: {date}
Sender email (for CRM lookup): {sender_email}

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
            "Any person or organization using one of these domains should be "
            "treated as internal. Do NOT create or update CRM contacts or "
            "organizations for them. Internal teammates may still appear in "
            "the headers or body as useful context, but focus CRM actions on "
            "external people and organizations."
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
