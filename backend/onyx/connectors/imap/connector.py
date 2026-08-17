import copy
import email
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import getaddresses
from enum import Enum
from typing import Any, cast
from urllib.parse import unquote

import bs4
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.imap.models import EmailHeaders
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    Document,
    TextSection,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

# Retry decorator for IMAP operations that may fail due to transient
# network issues (connection resets, timeouts, etc.).  Uses the same
# retry_builder utility as the Gmail connector with conservative defaults
# appropriate for IMAP's stateful connections.
_add_imap_retries = retry_builder(
    tries=5,
    delay=1,
    max_delay=10,
    backoff=2,
    exceptions=(
        OSError,  # covers ConnectionError, TimeoutError, socket errors
        imaplib.IMAP4.error,  # covers IMAP4.abort and IMAP4.readonly too
    ),
)

_DEFAULT_IMAP_PORT_NUMBER = int(os.environ.get("IMAP_PORT", 993))
# Without a socket timeout, imaplib blocks forever if the server goes silent
# mid-connection (observed with AWS WorkMail: an ESTABLISHED socket that never
# delivers bytes hung docfetching for 11 days). A timeout turns that into a
# TimeoutError, which _add_imap_retries handles.
_IMAP_SOCKET_TIMEOUT_SECONDS = int(os.environ.get("IMAP_SOCKET_TIMEOUT_SECONDS", 60))
_IMAP_OKAY_STATUS = "OK"
_PAGE_SIZE = 100
# IMAP has no per-message size guard the way the Gmail connector does (10 MB
# at the API layer), so cap the extracted body to keep pathological emails
# from ballooning indexing/CRM payloads.
_MAX_EMAIL_BODY_CHARS = 500_000
_USERNAME_KEY = "imap_username"
_PASSWORD_KEY = "imap_password"


class CurrentMailbox(BaseModel):
    mailbox: str
    todo_email_ids: list[str]


# An email has a list of mailboxes.
# Each mailbox has a list of email-ids inside of it.
#
# Usage:
# To use this checkpointer, first fetch all the mailboxes.
# Then, pop a mailbox and fetch all of its email-ids.
# Then, pop each email-id and fetch its content (and parse it, etc..).
# When you have popped all email-ids for this mailbox, pop the next mailbox and repeat the above process until you're done.
#
# For initial checkpointing, set both fields to `None`.
class ImapCheckpoint(ConnectorCheckpoint):
    todo_mailboxes: list[str] | None = None
    current_mailbox: CurrentMailbox | None = None


class LoginState(str, Enum):
    LoggedIn = "logged_in"
    LoggedOut = "logged_out"


class ImapConnector(
    CredentialsConnector,
    CheckpointedConnectorWithPermSync[ImapCheckpoint],
):
    def __init__(
        self,
        host: str,
        port: int = _DEFAULT_IMAP_PORT_NUMBER,
        mailboxes: list[str] | None = None,
        lookback_days: int | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._mailboxes = mailboxes
        # When set (>0), clamps the IMAP SINCE window so emails older than
        # `lookback_days` are invisible to the connector. This cooperates with
        # the existing connector-pruning flow (which calls the connector with
        # start=epoch 0) to effectively hard-delete aged-out emails from Vespa
        # and the Postgres Document table.
        self._lookback_days = lookback_days
        self._credentials: dict[str, Any] | None = None

    @property
    def credentials(self) -> dict[str, Any]:
        if not self._credentials:
            raise RuntimeError(
                "Credentials have not been initialized; call `set_credentials_provider` first"
            )
        return self._credentials

    def _get_mail_client(self) -> imaplib.IMAP4_SSL:
        """
        Returns a new `imaplib.IMAP4_SSL` instance.

        The `imaplib.IMAP4_SSL` object is supposed to be an "ephemeral" object; it's not something that you can login,
        logout, then log back into again. I.e., the following will fail:

        ```py
        mail_client.login(..)
        mail_client.logout();
        mail_client.login(..)
        ```

        Therefore, you need a fresh, new instance in order to operate with IMAP. This function gives one to you.

        # Notes
        This function will throw an error if the credentials have not yet been set.
        """

        def get_or_raise(name: str) -> str:
            value = self.credentials.get(name)
            if not value:
                raise RuntimeError(f"Credential item {name=} was not found")
            if not isinstance(value, str):
                raise RuntimeError(
                    f"Credential item {name=} must be of type str, instead received {type(name)=}"
                )
            return value

        username = get_or_raise(_USERNAME_KEY)
        password = get_or_raise(_PASSWORD_KEY)

        @_add_imap_retries
        def _connect_and_login() -> imaplib.IMAP4_SSL:
            client = imaplib.IMAP4_SSL(
                host=self._host, port=self._port, timeout=_IMAP_SOCKET_TIMEOUT_SECONDS
            )
            status, _data = client.login(user=username, password=password)
            if status != _IMAP_OKAY_STATUS:
                raise RuntimeError(f"Failed to log into imap server; {status=}")
            return client

        return _connect_and_login()

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
        include_perm_sync: bool,
    ) -> CheckpointOutput[ImapCheckpoint]:
        checkpoint = cast(ImapCheckpoint, copy.deepcopy(checkpoint))
        checkpoint.has_more = True

        mail_client = self._get_mail_client()

        try:
            if checkpoint.todo_mailboxes is None:
                # This is the dummy checkpoint.
                # Fill it with mailboxes first.
                if self._mailboxes:
                    checkpoint.todo_mailboxes = [m for m in self._mailboxes if m]
                else:
                    fetched_mailboxes = _fetch_all_mailboxes_for_email_account(
                        mail_client=mail_client
                    )
                    if not fetched_mailboxes:
                        raise RuntimeError(
                            "Failed to find any mailboxes for this email account"
                        )
                    checkpoint.todo_mailboxes = [m for m in fetched_mailboxes if m]

                return checkpoint

            if (
                not checkpoint.current_mailbox
                or not checkpoint.current_mailbox.todo_email_ids
            ):
                if not checkpoint.todo_mailboxes:
                    checkpoint.has_more = False
                    return checkpoint

                mailbox = checkpoint.todo_mailboxes.pop()
                email_ids = _fetch_email_ids_in_mailbox(
                    mail_client=mail_client,
                    mailbox=mailbox,
                    start=start,
                    end=end,
                    lookback_days=self._lookback_days,
                )
                checkpoint.current_mailbox = CurrentMailbox(
                    mailbox=mailbox,
                    todo_email_ids=email_ids,
                )

            _select_mailbox(
                mail_client=mail_client, mailbox=checkpoint.current_mailbox.mailbox
            )
            current_todos = cast(
                list,
                copy.deepcopy(checkpoint.current_mailbox.todo_email_ids[:_PAGE_SIZE]),
            )
            checkpoint.current_mailbox.todo_email_ids = (
                checkpoint.current_mailbox.todo_email_ids[_PAGE_SIZE:]
            )

            for email_id in current_todos:
                email_msg = _fetch_email(mail_client=mail_client, email_id=email_id)
                if not email_msg:
                    logger.warning(
                        "Failed to fetch message email_id=%s; skipping", email_id
                    )
                    continue

                email_headers = EmailHeaders.from_email_msg(email_msg=email_msg)

                yield _convert_email_headers_and_body_into_document(
                    email_msg=email_msg,
                    email_headers=email_headers,
                    include_perm_sync=include_perm_sync,
                )

            return checkpoint
        finally:
            mail_client.logout()

    # impls for BaseConnector

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use `set_credentials_provider` instead")

    def validate_connector_settings(self) -> None:
        self._get_mail_client()

    # impls for CredentialsConnector

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._credentials = credentials_provider.get_credentials()

    # impls for CheckpointedConnector

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
    ) -> CheckpointOutput[ImapCheckpoint]:
        return self._load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint, include_perm_sync=False
        )

    def build_dummy_checkpoint(self) -> ImapCheckpoint:
        return ImapCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> ImapCheckpoint:
        return ImapCheckpoint.model_validate_json(json_data=checkpoint_json)

    # impls for CheckpointedConnectorWithPermSync

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
    ) -> CheckpointOutput[ImapCheckpoint]:
        return self._load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint, include_perm_sync=True
        )


@_add_imap_retries
def _fetch_all_mailboxes_for_email_account(mail_client: imaplib.IMAP4_SSL) -> list[str]:
    status, mailboxes_data = mail_client.list(directory="", pattern="*")
    if status != _IMAP_OKAY_STATUS:
        raise RuntimeError(f"Failed to fetch mailboxes; {status=}")

    mailboxes = []

    for mailboxes_raw in mailboxes_data:
        if isinstance(mailboxes_raw, bytes):
            mailboxes_str = mailboxes_raw.decode()
        elif isinstance(mailboxes_raw, str):
            mailboxes_str = mailboxes_raw
        else:
            logger.warning(
                "Expected the mailbox data to be of type str, instead got type(mailboxes_raw)=%r %s; skipping",
                type(mailboxes_raw),
                mailboxes_raw,
            )
            continue

        # The mailbox LIST response output can be found here:
        # https://www.rfc-editor.org/rfc/rfc3501.html#section-7.2.2
        #
        # The general format is:
        # `(<name-attributes>) <hierarchy-delimiter> <mailbox-name>`
        #
        # The below regex matches on that pattern; from there, we select the 3rd match (index 2), which is the mailbox-name.
        match = re.match(r'\(([^)]*)\)\s+"([^"]+)"\s+"?(.+?)"?$', mailboxes_str)
        if not match:
            logger.warning(
                "Invalid mailbox-data formatting structure: mailboxes_str=%r; skipping",
                mailboxes_str,
            )
            continue

        attributes = match.group(1)
        if r"\Noselect" in attributes:
            continue

        mailbox = match.group(3).strip('"')
        mailboxes.append(mailbox)

    return mailboxes


def _imap_quote_mailbox(mailbox: str) -> str:
    """Quote a mailbox name for IMAP protocol use.

    Python 3's imaplib does NOT auto-quote mailbox names (CPython bug #92835),
    so names with spaces (e.g. '[Gmail]/Sent Mail') must be explicitly quoted.
    Strips any existing quotes first to handle stale checkpoint data.
    """
    mailbox = mailbox.strip('"')
    return f'"{mailbox}"'


def _select_mailbox(mail_client: imaplib.IMAP4_SSL, mailbox: str) -> None:
    quoted = _imap_quote_mailbox(mailbox)
    status, _ids = mail_client.select(mailbox=quoted, readonly=True)
    if status != _IMAP_OKAY_STATUS:
        raise RuntimeError(f"Failed to select {mailbox=}")


@_add_imap_retries
def _fetch_email_ids_in_mailbox(
    mail_client: imaplib.IMAP4_SSL,
    mailbox: str,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    lookback_days: int | None = None,
) -> list[str]:
    try:
        _select_mailbox(mail_client=mail_client, mailbox=mailbox)
    except RuntimeError:
        logger.warning("Skipping non-selectable mailbox: %s", mailbox)
        return []

    # Retention clamp: when lookback_days is set and positive, emails older
    # than `now - lookback_days` are invisible to the connector regardless
    # of the caller-provided `start`. For steady-state indexing polls this
    # is a no-op (start is already recent); for pruning (which passes
    # start=epoch 0) it causes aged-out emails to disappear from the
    # connector's view, so the diff computation in the pruning pipeline
    # classifies them as to-be-removed and the existing deletion path
    # removes them from Vespa and Postgres.
    if lookback_days is not None and lookback_days > 0:
        retention_cutoff = datetime.now(tz=timezone.utc).timestamp() - (
            lookback_days * 86400
        )
        start = max(start, retention_cutoff)

    start_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%d-%b-%Y")
    # IMAP BEFORE uses date-only granularity (excludes the given date),
    # so add 1 day to include emails from the end date itself.
    end_dt = datetime.fromtimestamp(end, tz=timezone.utc) + timedelta(days=1)
    end_str = end_dt.strftime("%d-%b-%Y")
    search_criteria = f'(SINCE "{start_str}" BEFORE "{end_str}")'

    status, email_ids_byte_array = mail_client.search(None, search_criteria)

    if status != _IMAP_OKAY_STATUS or not email_ids_byte_array:
        raise RuntimeError(f"Failed to fetch email ids; {status=}")

    email_ids: bytes = email_ids_byte_array[0]

    return [email_id.decode() for email_id in email_ids.split()]


@_add_imap_retries
def _fetch_email(mail_client: imaplib.IMAP4_SSL, email_id: str) -> Message | None:
    status, msg_data = mail_client.fetch(message_set=email_id, message_parts="(RFC822)")
    if status != _IMAP_OKAY_STATUS or not msg_data:
        return None

    data = msg_data[0]
    if not isinstance(data, tuple):
        raise RuntimeError(
            f"Message data should be a tuple; instead got a {type(data)=} {data=}"
        )

    _metadata, raw_email = data
    return email.message_from_bytes(raw_email)


def _convert_email_headers_and_body_into_document(
    email_msg: Message,
    email_headers: EmailHeaders,
    include_perm_sync: bool,
) -> Document:
    sender_name, sender_addr = _parse_singular_addr(raw_header=email_headers.sender)
    parsed_recipients = (
        _parse_addrs(raw_header=email_headers.recipients)
        if email_headers.recipients
        else []
    )

    # Mirror the Gmail connector's convention (and what the email-CRM payload
    # builder expects): sender in primary_owners, recipients in
    # secondary_owners. Lumping recipients into primary_owners left the CRM
    # prompt's "To:" line permanently empty for IMAP mail. The two sets are
    # independent: a self-addressed sender stays a recipient too.
    recipient_info_map = {
        recipient_addr: BasicExpertInfo(
            display_name=recipient_name, email=recipient_addr
        )
        for recipient_name, recipient_addr in parsed_recipients
    }

    email_body = _parse_email_body(email_msg=email_msg, email_headers=email_headers)
    primary_owners = [BasicExpertInfo(display_name=sender_name, email=sender_addr)]
    secondary_owners = list(recipient_info_map.values())
    external_access = (
        ExternalAccess(
            external_user_emails={sender_addr, *recipient_info_map.keys()},
            external_user_group_ids=set(),
            is_public=False,
        )
        if include_perm_sync
        else None
    )

    # Prepend structured header context so the LLM (and search) can see
    # who the email is from/to, matching the pattern used by the Gmail connector.
    header_lines = f"from: {email_headers.sender}\n"
    if email_headers.recipients:
        header_lines += f"to: {email_headers.recipients}\n"
    header_lines += f"subject: {email_headers.subject}\n"
    header_lines += f"date: {email_headers.date.isoformat()}\n"
    section_text = f"{header_lines}\n{email_body}"

    return Document(
        id=email_headers.id,
        title=email_headers.subject,
        semantic_identifier=email_headers.subject,
        metadata={},
        source=DocumentSource.IMAP,
        sections=[TextSection(text=section_text)],
        doc_updated_at=(
            email_headers.date.astimezone(timezone.utc) if email_headers.date else None
        ),
        primary_owners=primary_owners,
        secondary_owners=secondary_owners,
        external_access=external_access,
    )


def _iter_candidate_body_parts(part: Message) -> list[Message]:
    """Leaf text parts that belong to THIS message's body.

    Message.walk() descends into attached content — an attached .eml
    (message/rfc822) or attached multipart container yields children with no
    attachment disposition of their own, letting an attachment's body shadow
    the real one. Recursing manually lets a part inherit its ancestor's
    attachment status.
    """
    if part.get_content_disposition() == "attachment":
        return []
    if part.is_multipart():
        leaf_parts: list[Message] = []
        for sub_part in part.get_payload():
            if isinstance(sub_part, Message):
                leaf_parts.extend(_iter_candidate_body_parts(sub_part))
        return leaf_parts
    return [part]


def _parse_email_body(
    email_msg: Message,
    email_headers: EmailHeaders,
) -> str:
    plain_body = None
    html_body = None
    for part in _iter_candidate_body_parts(email_msg):
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue

        charset = part.get_content_charset() or "utf-8"

        raw_payload = part.get_payload(decode=True)
        if not isinstance(raw_payload, bytes):
            logger.warning(
                "Payload section from email was expected to be an array of bytes, instead got type(raw_payload)=%r, raw_payload=%r",
                type(raw_payload),
                raw_payload,
            )
            continue
        try:
            decoded = raw_payload.decode(charset)
        except (UnicodeDecodeError, LookupError) as e:
            logger.warning(
                "Could not decode part with charset %s (%s); retrying as utf-8 with replacement",
                charset,
                e,
            )
            decoded = raw_payload.decode("utf-8", errors="replace")

        # Keep the first NON-BLANK candidate of each type: a blank first part
        # must not mask a real body later in the message.
        if not decoded.strip():
            continue
        if content_type == "text/plain" and plain_body is None:
            plain_body = decoded
        elif content_type == "text/html" and html_body is None:
            html_body = decoded

        if plain_body is not None:
            # Plain is always preferred; no need to keep scanning.
            break

    # Plain text must be returned verbatim: running it through an HTML parser
    # deletes angle-bracketed addresses ("Frank <frank@example.com>" in quoted
    # forward headers) as if they were tags, and flattens the line structure
    # the LLM needs to read quoted headers.
    if plain_body:
        return plain_body.replace("\r\n", "\n").strip()[:_MAX_EMAIL_BODY_CHARS]

    if html_body:
        return _email_html_to_text(html_body)[:_MAX_EMAIL_BODY_CHARS]

    logger.warning(
        "Email with email_headers.id=%r has an empty body; returning an empty string",
        email_headers.id,
    )
    return ""


# Tags that imply a line break when HTML email is rendered as text.
_HTML_BLOCK_TAGS = [
    "blockquote",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "table",
    "tr",
    "ul",
]


def _email_html_to_text(html_body: str) -> str:
    """Self-contained HTML-to-text for email bodies.

    Deliberately does NOT use html_utils.format_document_soup: its output
    depends on the global link-transform strategy (under "markdown" it wraps
    every text fragment near an anchor into mailto links) and its closing-tag
    handling is unreachable with BeautifulSoup descendants, leaking table
    state into subsequent content.
    """
    soup = bs4.BeautifulSoup(markup=html_body, features="html.parser")

    for tag in soup.find_all(["script", "style", "head", "title"]):
        tag.decompose()

    # <a href="mailto:frank@example.com">Frank</a> renders as just "Frank";
    # the href is often the only place a participant's address appears, so
    # inject it into the anchor text before flattening.
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if isinstance(href, list):
            href = href[0] if href else None
        if not isinstance(href, str) or not href.lower().startswith("mailto:"):
            continue
        addr = unquote(href[len("mailto:") :].split("?", 1)[0].strip())
        if addr and addr.lower() not in anchor.get_text().lower():
            anchor.append(f" <{addr}>")

    for tag in soup.find_all(_HTML_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    for tag in soup.find_all(["td", "th"]):
        tag.insert_after(" ")

    text = soup.get_text()
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    collapsed: list[str] = []
    for line in lines:
        # Allow at most one consecutive blank line.
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip()


def _parse_addrs(raw_header: str) -> list[tuple[str, str]]:
    # getaddresses handles quoted display names containing commas
    # ('"Doe, Jane" <jane@example.com>') and address groups, which naive
    # comma-splitting + parseaddr silently mangled.
    return [(name, addr) for name, addr in getaddresses([raw_header]) if addr]


def _parse_singular_addr(raw_header: str) -> tuple[str, str]:
    addrs = _parse_addrs(raw_header=raw_header)
    if not addrs:
        raise RuntimeError(
            f"Parsing email header resulted in no addresses being found; {raw_header=}"
        )
    elif len(addrs) >= 2:
        raise RuntimeError(
            f"Expected a singular address, but instead got multiple; {raw_header=} {addrs=}"
        )

    return addrs[0]


if __name__ == "__main__":
    import time

    from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
    from tests.daily.connectors.utils import load_all_from_connector

    host = os.environ.get("IMAP_HOST")
    mailboxes_str = os.environ.get("IMAP_MAILBOXES")
    username = os.environ.get("IMAP_USERNAME")
    password = os.environ.get("IMAP_PASSWORD")

    mailboxes = (
        [mailbox.strip() for mailbox in mailboxes_str.split(",")]
        if mailboxes_str
        else []
    )

    if not host:
        raise RuntimeError("`IMAP_HOST` must be set")

    imap_connector = ImapConnector(
        host=host,
        mailboxes=mailboxes,
    )

    imap_connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={
                _USERNAME_KEY: username,
                _PASSWORD_KEY: password,
            },
        )
    )

    for doc in load_all_from_connector(
        connector=imap_connector,
        start=0,
        end=time.time(),
    ).documents:
        print(doc)
