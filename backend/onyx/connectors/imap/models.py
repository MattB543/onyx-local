import email.errors
import email.header
import email.utils
from datetime import datetime
from email.message import Message
from enum import Enum

from pydantic import BaseModel


class Header(str, Enum):
    SUBJECT_HEADER = "subject"
    FROM_HEADER = "from"
    TO_HEADER = "to"
    DELIVERED_TO_HEADER = (
        "Delivered-To"  # Used in mailing lists instead of the "to" header.
    )
    DATE_HEADER = "date"
    MESSAGE_ID_HEADER = "Message-ID"


class EmailHeaders(BaseModel):
    """
    Model for email headers extracted from IMAP messages.
    """

    id: str
    subject: str
    sender: str
    recipients: str | None
    date: datetime

    @classmethod
    def from_email_msg(cls, email_msg: Message) -> "EmailHeaders":
        def _decode(header: str, default: str | None = None) -> str | None:
            value = email_msg.get(header, default)
            if not value:
                return None

            # decode_header returns a LIST of fragments; a header like
            # '=?UTF-8?Q?Frank_McCourt?= <frank@example.com>' decodes to an
            # encoded display-name fragment followed by a literal address
            # fragment. Taking only fragment [0] silently dropped the address.
            try:
                fragments = email.header.decode_header(value)
            except email.errors.HeaderParseError:
                return value

            try:
                return str(email.header.make_header(fragments))
            except (LookupError, UnicodeDecodeError, email.errors.HeaderParseError):
                # Unknown/broken charset in some fragment: decode leniently.
                decoded_parts = []
                for decoded_value, encoding in fragments:
                    if isinstance(decoded_value, bytes):
                        try:
                            decoded_parts.append(
                                decoded_value.decode(
                                    encoding or "utf-8", errors="replace"
                                )
                            )
                        except LookupError:
                            # The charset itself is unknown to Python
                            # (e.g. '=?x-unknown?...?='); errors="replace"
                            # can't help with that.
                            decoded_parts.append(
                                decoded_value.decode("utf-8", errors="replace")
                            )
                    else:
                        decoded_parts.append(decoded_value)
                return "".join(decoded_parts) or None

        def _parse_date(date_str: str | None) -> datetime | None:
            if not date_str:
                return None
            try:
                return email.utils.parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                return None

        message_id = _decode(header=Header.MESSAGE_ID_HEADER)
        # It's possible for the subject line to not exist or be an empty string.
        subject = _decode(header=Header.SUBJECT_HEADER) or "Unknown Subject"
        from_ = _decode(header=Header.FROM_HEADER)
        to = _decode(header=Header.TO_HEADER)
        if not to:
            to = _decode(header=Header.DELIVERED_TO_HEADER)
        date_str = _decode(header=Header.DATE_HEADER)
        date = _parse_date(date_str=date_str)

        # If any of the above are `None`, model validation will fail.
        # Therefore, no guards (i.e.: `if <header> is None: raise RuntimeError(..)`) were written.
        return cls.model_validate(
            {
                "id": message_id,
                "subject": subject,
                "sender": from_,
                "recipients": to,
                "date": date,
            }
        )
