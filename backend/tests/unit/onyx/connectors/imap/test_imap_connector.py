from __future__ import annotations

import email
from datetime import datetime, timezone
from email.message import Message
from unittest.mock import MagicMock, patch

from onyx.connectors.imap.connector import (
    _convert_email_headers_and_body_into_document,
    _fetch_email_ids_in_mailbox,
    _parse_addrs,
    _parse_email_body,
)
from onyx.connectors.imap.models import EmailHeaders


def _make_mail_client(search_return: tuple[str, list[bytes]]) -> MagicMock:
    """Build a mocked imaplib.IMAP4_SSL that returns the given
    (status, data) tuple from .search(...) and always succeeds on
    .select(...). .search is what we introspect for the SINCE/BEFORE
    criteria in these tests."""
    mail_client = MagicMock()
    # .select must succeed so _select_mailbox does not raise.
    mail_client.select.return_value = ("OK", [b""])
    mail_client.search.return_value = search_return
    return mail_client


def _extract_search_criteria(mail_client: MagicMock) -> str:
    """Pull the search criteria string out of the last .search(...) call."""
    assert mail_client.search.called, "Expected mail_client.search to be called"
    _charset, criteria = mail_client.search.call_args.args
    return criteria


def test_fetch_email_ids_in_mailbox_without_lookback_days_is_unchanged() -> None:
    """When lookback_days is not provided, the caller-supplied `start` is
    used verbatim as the IMAP SINCE value (no retention clamp)."""
    mail_client = _make_mail_client(("OK", [b"1 2 3"]))
    start = 1_700_000_000.0  # Fixed UNIX timestamp -- Tue, 14 Nov 2023 UTC
    end = 1_700_500_000.0  # ~Mon, 20 Nov 2023 UTC

    email_ids = _fetch_email_ids_in_mailbox(
        mail_client=mail_client,
        mailbox="INBOX",
        start=start,
        end=end,
    )

    assert email_ids == ["1", "2", "3"]
    criteria = _extract_search_criteria(mail_client)
    # Unmodified start corresponds to 14-Nov-2023 in UTC.
    assert 'SINCE "14-Nov-2023"' in criteria
    # end (+ 1 day) is 21-Nov-2023.
    assert 'BEFORE "21-Nov-2023"' in criteria


def test_fetch_email_ids_in_mailbox_with_lookback_days_clamps_start() -> None:
    """When start is far in the past (e.g. epoch 0 from the pruning path)
    and lookback_days is set, the SINCE date is clamped to
    `now - lookback_days`."""
    fake_now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    mail_client = _make_mail_client(("OK", [b""]))

    with patch(
        "onyx.connectors.imap.connector.datetime",
        wraps=datetime,
    ) as mock_datetime:
        # datetime.now(tz=...) -> fake_now; datetime.fromtimestamp(...)
        # still needs to behave normally, which is why we wrap datetime.
        mock_datetime.now.return_value = fake_now

        _fetch_email_ids_in_mailbox(
            mail_client=mail_client,
            mailbox="INBOX",
            start=0.0,  # epoch 0 -- pruning path
            end=fake_now.timestamp(),
            lookback_days=7,
        )

    criteria = _extract_search_criteria(mail_client)
    # 2026-04-21 minus 7 days = 2026-04-14
    assert 'SINCE "14-Apr-2026"' in criteria


def test_fetch_email_ids_in_mailbox_lookback_noop_when_start_is_recent() -> None:
    """When the caller-supplied `start` is already more recent than
    `now - lookback_days`, the clamp is a no-op and the original `start`
    is used."""
    fake_now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)
    # start = now - 1 hour, which is WELL inside the 7-day window.
    recent_start = fake_now.timestamp() - 3600
    mail_client = _make_mail_client(("OK", [b""]))

    with patch(
        "onyx.connectors.imap.connector.datetime",
        wraps=datetime,
    ) as mock_datetime:
        mock_datetime.now.return_value = fake_now

        _fetch_email_ids_in_mailbox(
            mail_client=mail_client,
            mailbox="INBOX",
            start=recent_start,
            end=fake_now.timestamp(),
            lookback_days=7,
        )

    criteria = _extract_search_criteria(mail_client)
    # Caller's start (2026-04-21 11:00 UTC) renders as 21-Apr-2026.
    assert 'SINCE "21-Apr-2026"' in criteria
    # And should NOT have been clamped back to the 7-day-ago date
    # (14-Apr-2026) -- assert explicitly for regression protection.
    assert 'SINCE "14-Apr-2026"' not in criteria


def test_fetch_email_ids_in_mailbox_lookback_zero_is_disabled() -> None:
    """A zero lookback is treated as disabled, so the caller-supplied
    `start` is used unchanged."""
    mail_client = _make_mail_client(("OK", [b"4 5"]))
    start = 1_700_000_000.0
    end = 1_700_500_000.0

    email_ids = _fetch_email_ids_in_mailbox(
        mail_client=mail_client,
        mailbox="INBOX",
        start=start,
        end=end,
        lookback_days=0,
    )

    assert email_ids == ["4", "5"]
    criteria = _extract_search_criteria(mail_client)
    assert 'SINCE "14-Nov-2023"' in criteria
    assert 'BEFORE "21-Nov-2023"' in criteria


def test_fetch_email_ids_in_mailbox_lookback_none_is_disabled() -> None:
    """A null lookback is treated as disabled, so the caller-supplied
    `start` is used unchanged."""
    mail_client = _make_mail_client(("OK", [b"6 7"]))
    start = 1_700_000_000.0
    end = 1_700_500_000.0

    email_ids = _fetch_email_ids_in_mailbox(
        mail_client=mail_client,
        mailbox="INBOX",
        start=start,
        end=end,
        lookback_days=None,
    )

    assert email_ids == ["6", "7"]
    criteria = _extract_search_criteria(mail_client)
    assert 'SINCE "14-Nov-2023"' in criteria
    assert 'BEFORE "21-Nov-2023"' in criteria


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------


def _mime_message(raw: str) -> Message:
    return email.message_from_string(raw)


_HEADERS = EmailHeaders(
    id="<test-id@example.com>",
    subject="Test Subject",
    sender="Sender <sender@example.com>",
    recipients="Recipient <recipient@example.com>",
    date=datetime(2026, 7, 13, 20, 13, 7, tzinfo=timezone.utc),
)


def test_parse_email_body_plain_preserves_angle_addresses_and_newlines() -> None:
    """Regression: plain-text bodies were run through an HTML parser, which
    deleted angle-bracketed addresses in quoted forward headers (treated as
    tags) and flattened all newlines."""
    raw = (
        "From: anthony@futureoflife.org\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "fwding to capture contact info\r\n"
        "\r\n"
        '> From: "Frank McCourt" <frank@mccourtglobal.com>\r\n'
        '> To: "Tomicah Tillemann" <tomicah@projectliberty.io>\r\n'
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    # Exact verbatim output (CRLF normalized, outer whitespace stripped).
    assert body == (
        "fwding to capture contact info\n"
        "\n"
        '> From: "Frank McCourt" <frank@mccourtglobal.com>\n'
        '> To: "Tomicah Tillemann" <tomicah@projectliberty.io>'
    )


def test_parse_email_body_multipart_prefers_plain_over_html() -> None:
    raw = (
        'Content-Type: multipart/alternative; boundary="b"\r\n'
        "\r\n"
        "--b\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "plain version <frank@example.com>\r\n"
        "--b\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        "<p>html version</p>\r\n"
        "--b--\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "plain version <frank@example.com>" in body
    assert "html version" not in body


def test_parse_email_body_blank_plain_falls_back_to_html() -> None:
    raw = (
        'Content-Type: multipart/alternative; boundary="b"\r\n'
        "\r\n"
        "--b\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "   \r\n"
        "--b\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        "<p>html content here</p>\r\n"
        "--b--\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "html content here" in body


def test_parse_email_body_html_mailto_address_is_preserved() -> None:
    """<a href="mailto:...">Name</a> must keep the address, not just the
    display text."""
    raw = (
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        '<p>Contact <a href="mailto:frank@mccourtglobal.com?subject=hi">Frank'
        "</a> for details.</p>\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "Frank <frank@mccourtglobal.com>" in body
    assert "for details." in body
    # No markdown-link mangling or duplicated addresses.
    assert "](mailto" not in body
    assert body.count("frank@mccourtglobal.com") == 1


def test_parse_email_body_html_entity_encoded_address_survives() -> None:
    raw = (
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        "<p>From: Frank &lt;frank@example.com&gt;</p>\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "frank@example.com" in body


def test_parse_email_body_bad_charset_falls_back_instead_of_dropping() -> None:
    """A bogus charset used to drop the whole part; now it decodes leniently."""
    raw = (
        "Content-Type: text/plain; charset=not-a-real-charset\r\n"
        "\r\n"
        "important content <frank@example.com>\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "important content <frank@example.com>" in body


def test_parse_email_body_skips_text_attachments() -> None:
    raw = (
        'Content-Type: multipart/mixed; boundary="b"\r\n'
        "\r\n"
        "--b\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "actual body\r\n"
        "--b\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        'Content-Disposition: attachment; filename="notes.txt"\r\n'
        "\r\n"
        "attachment content\r\n"
        "--b--\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "actual body" in body
    assert "attachment content" not in body


# ---------------------------------------------------------------------------
# Address / header parsing
# ---------------------------------------------------------------------------


def test_parse_addrs_handles_quoted_comma_display_names() -> None:
    header = '"Doe, Jane" <jane@example.com>, Bob <bob@example.com>'
    parsed = _parse_addrs(raw_header=header)

    assert ("Doe, Jane", "jane@example.com") in parsed
    assert ("Bob", "bob@example.com") in parsed
    assert len(parsed) == 2


def test_email_headers_encoded_display_name_keeps_address() -> None:
    """Regression: decode_header(...)[0] dropped everything after the first
    fragment, losing the literal '<frank@example.com>' that follows an
    RFC 2047-encoded display name."""
    raw = (
        "Message-ID: <mid@example.com>\r\n"
        "Subject: =?UTF-8?Q?Caf=C3=A9_Meeting?=\r\n"
        "From: =?UTF-8?Q?Frank_McCourt?= <frank@example.com>\r\n"
        "To: =?UTF-8?Q?Tomicah_Tillemann?= <tomicah@example.com>\r\n"
        "Date: Mon, 13 Jul 2026 20:13:07 +0000\r\n"
        "\r\n"
        "body\r\n"
    )
    headers = EmailHeaders.from_email_msg(email_msg=_mime_message(raw))

    assert "frank@example.com" in headers.sender
    assert "Frank McCourt" in headers.sender
    assert headers.recipients is not None
    assert "tomicah@example.com" in headers.recipients
    assert headers.subject == "Café Meeting"


# ---------------------------------------------------------------------------
# Document conversion: owner split
# ---------------------------------------------------------------------------


def test_convert_document_splits_sender_and_recipients() -> None:
    """Sender goes to primary_owners, recipients to secondary_owners
    (mirroring the Gmail connector); previously everyone was lumped into
    primary_owners and the CRM payload's 'to' field was always empty."""
    raw = "Content-Type: text/plain; charset=utf-8\r\n\r\nbody text\r\n"
    headers = EmailHeaders(
        id="<mid@example.com>",
        subject="Subject",
        sender="Sender <sender@example.com>",
        recipients=(
            "Alice <alice@example.com>, Bob <bob@example.com>, "
            "Sender <sender@example.com>"
        ),
        date=datetime(2026, 7, 13, 20, 13, 7, tzinfo=timezone.utc),
    )

    doc = _convert_email_headers_and_body_into_document(
        email_msg=_mime_message(raw),
        email_headers=headers,
        include_perm_sync=True,
    )

    assert [o.email for o in doc.primary_owners or []] == ["sender@example.com"]
    # The owner sets are independent: a sender who is also an addressee
    # remains in the recipient list (matches Gmail connector behavior).
    assert sorted(o.email for o in doc.secondary_owners or []) == [
        "alice@example.com",
        "bob@example.com",
        "sender@example.com",
    ]
    # Permission sync still covers all participants.
    assert doc.external_access is not None
    assert doc.external_access.external_user_emails == {
        "sender@example.com",
        "alice@example.com",
        "bob@example.com",
    }


def test_parse_email_body_blank_first_plain_part_does_not_mask_later_one() -> None:
    """A blank text/plain part must not cause a later non-blank plain part
    (or worse, an empty result) to be skipped."""
    raw = (
        'Content-Type: multipart/mixed; boundary="b"\r\n'
        "\r\n"
        "--b\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "   \r\n"
        "--b\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "real body <frank@example.com>\r\n"
        "--b--\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert body == "real body <frank@example.com>"


def test_parse_email_body_attached_eml_does_not_shadow_real_body() -> None:
    """walk() descends into attached message/rfc822 parts whose children have
    no attachment disposition; their text must not replace the real body."""
    raw = (
        'Content-Type: multipart/mixed; boundary="outer"\r\n'
        "\r\n"
        "--outer\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        "<p>the real html body</p>\r\n"
        "--outer\r\n"
        "Content-Type: message/rfc822\r\n"
        'Content-Disposition: attachment; filename="old.eml"\r\n'
        "\r\n"
        "From: someone@example.com\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "attached email plain body\r\n"
        "--outer--\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "the real html body" in body
    assert "attached email plain body" not in body


def test_email_headers_unknown_charset_does_not_raise() -> None:
    raw = (
        "Message-ID: <mid2@example.com>\r\n"
        "Subject: =?x-unknown-charset?B?aGVsbG8=?=\r\n"
        "From: Frank <frank@example.com>\r\n"
        "To: tomicah@example.com\r\n"
        "Date: Mon, 13 Jul 2026 20:13:07 +0000\r\n"
        "\r\n"
        "body\r\n"
    )
    headers = EmailHeaders.from_email_msg(email_msg=_mime_message(raw))

    # Lenient decode: must produce SOME subject rather than raising.
    assert headers.subject
    assert "frank@example.com" in headers.sender


def test_email_html_to_text_table_does_not_swallow_following_content() -> None:
    raw = (
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        "<table><tr><td>cell1</td><td>cell2</td></tr></table>"
        "<p>after the table</p>\r\n"
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "cell1" in body and "cell2" in body
    # Content following a table must land on its own line, not be
    # concatenated into the last cell.
    assert body.splitlines()[-1] == "after the table"


def test_email_html_to_text_percent_encoded_mailto_is_decoded() -> None:
    raw = (
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        '<p><a href="mailto:frank%40example.com">Frank</a></p>\r\n'
    )
    body = _parse_email_body(email_msg=_mime_message(raw), email_headers=_HEADERS)

    assert "Frank <frank@example.com>" in body
