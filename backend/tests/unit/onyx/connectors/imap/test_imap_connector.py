from __future__ import annotations

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.imap.connector import _fetch_email_ids_in_mailbox


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
