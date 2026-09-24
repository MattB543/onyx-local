"""Lets the uploader read a chat upload before a chat message references it.

The composer asks for `GET /chat/file/{file_id}` right after
`POST /chat/files/upload`. The user message that puts the file in
`ChatMessage.files` is committed later, inside the stream, so the previews
got a 404. Now the uploader can read a `CHAT_UPLOAD` row whose
`uploaded_by_user_id` is equal to their id. Rows without an owner, and the
shared anonymous user, do not get this access.
"""

from collections.abc import Generator
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.access.access import user_can_access_chat_file
from onyx.auth.users import get_anonymous_user
from onyx.chat.chat_file_utils import (
    build_chat_upload_metadata,
    update_chat_upload_file_metadata,
)
from onyx.configs.constants import ANONYMOUS_USER_UUID, FileOrigin, MessageType
from onyx.db.chat import create_chat_session
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import ChatMessage, ChatSession, FileRecord, User
from onyx.file_store.models import ChatFileType, FileDescriptor
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


class _Users(NamedTuple):
    owner: User
    other: User
    created_file_ids: list[str]


@pytest.fixture
def users(db_session: Session) -> Generator[_Users, None, None]:
    owner = create_test_user(db_session, "chat-upload-owner")
    other = create_test_user(db_session, "chat-upload-other")
    created = _Users(owner=owner, other=other, created_file_ids=[])
    yield created
    db_session.rollback()
    db_session.query(FileRecord).filter(
        FileRecord.file_id.in_(created.created_file_ids)
    ).delete(synchronize_session=False)
    session_ids = [
        session_id
        for (session_id,) in db_session.query(ChatSession.id).filter(
            ChatSession.user_id.in_([owner.id, other.id])
        )
    ]
    db_session.query(ChatMessage).filter(
        ChatMessage.chat_session_id.in_(session_ids)
    ).delete(synchronize_session=False)
    db_session.query(ChatSession).filter(ChatSession.id.in_(session_ids)).delete(
        synchronize_session=False
    )
    delete_test_user(db_session, owner, other)
    db_session.commit()


def _add_file_record(
    db_session: Session,
    file_origin: FileOrigin = FileOrigin.CHAT_UPLOAD,
    file_metadata: dict[str, Any] | None = None,
) -> str:
    file_id = str(uuid4())
    db_session.add(
        FileRecord(
            file_id=file_id,
            display_name="pasted.png",
            file_origin=file_origin,
            file_type="image/png",
            file_metadata=file_metadata,
            bucket_name="test-bucket",
            object_key=file_id,
        )
    )
    db_session.flush()
    return file_id


def _seed_chat_upload(
    db_session: Session,
    users: _Users,
    uploaded_by_user_id: UUID | None,
    file_origin: FileOrigin = FileOrigin.CHAT_UPLOAD,
) -> str:
    """Write the row the same way `POST /chat/files/upload` does."""
    file_id = _add_file_record(db_session, file_origin=file_origin)
    update_chat_upload_file_metadata(
        file_id=file_id,
        metadata=build_chat_upload_metadata(
            uploaded_by_user_id=uploaded_by_user_id,
            original_content_type="image/png",
            token_count=None,
        ),
        db_session=db_session,
    )
    db_session.commit()
    users.created_file_ids.append(file_id)
    return file_id


def test_uploader_can_read_their_chat_upload(
    db_session: Session, users: _Users
) -> None:
    file_id = _seed_chat_upload(db_session, users, users.owner.id)

    assert user_can_access_chat_file(file_id, users.owner, db_session)


def test_other_user_cannot_read_a_chat_upload(
    db_session: Session, users: _Users
) -> None:
    file_id = _seed_chat_upload(db_session, users, users.owner.id)

    assert not user_can_access_chat_file(file_id, users.other, db_session)


def test_owner_id_on_a_file_that_is_not_a_chat_upload_gives_no_access(
    db_session: Session, users: _Users
) -> None:
    file_id = _seed_chat_upload(
        db_session, users, users.owner.id, file_origin=FileOrigin.OTHER
    )

    assert not user_can_access_chat_file(file_id, users.owner, db_session)


@pytest.mark.parametrize(
    "file_metadata",
    [
        None,
        build_chat_upload_metadata(
            uploaded_by_user_id=None,
            original_content_type="image/png",
            token_count=None,
        ),
    ],
    ids=["no_metadata", "null_owner_id"],
)
def test_ownerless_legacy_chat_upload_is_denied(
    db_session: Session, users: _Users, file_metadata: dict[str, Any] | None
) -> None:
    file_id = _add_file_record(db_session, file_metadata=file_metadata)
    db_session.commit()
    users.created_file_ids.append(file_id)

    assert not user_can_access_chat_file(file_id, users.owner, db_session)


def test_anonymous_user_cannot_read_an_anonymous_chat_upload(
    db_session: Session, users: _Users
) -> None:
    # All anonymous visitors share this id, so an equal id does not show
    # that the reader is the uploader.
    file_id = _seed_chat_upload(db_session, users, UUID(ANONYMOUS_USER_UUID))
    anonymous_user = get_anonymous_user()
    assert anonymous_user.is_anonymous

    assert not user_can_access_chat_file(file_id, anonymous_user, db_session)


def test_public_shared_chat_still_shares_its_uploads(
    db_session: Session, users: _Users
) -> None:
    file_id = _seed_chat_upload(db_session, users, users.owner.id)
    session = create_chat_session(
        db_session=db_session,
        description="chat upload access",
        user_id=users.owner.id,
        persona_id=None,
    )
    db_session.add(
        ChatMessage(
            chat_session_id=session.id,
            message="look at this",
            token_count=0,
            message_type=MessageType.USER,
            files=[
                FileDescriptor(id=file_id, type=ChatFileType.IMAGE, name="pasted.png")
            ],
        )
    )
    db_session.commit()
    assert not user_can_access_chat_file(file_id, users.other, db_session)

    session.shared_status = ChatSessionSharedStatus.PUBLIC
    db_session.commit()

    assert user_can_access_chat_file(file_id, users.other, db_session)


@pytest.fixture
def other_tenant_schema(db_session: Session) -> Generator[str, None, None]:
    """A second tenant schema with the tables that the upload check reads."""
    schema = f"test_tenant_{uuid4().hex[:12]}"
    db_session.execute(text(f'CREATE SCHEMA "{schema}"'))
    for table in ("user_file", "file_record"):
        db_session.execute(
            text(f'CREATE TABLE "{schema}".{table} (LIKE public.{table} INCLUDING ALL)')
        )
    db_session.commit()
    yield schema
    db_session.rollback()
    db_session.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    db_session.commit()


def test_chat_upload_is_not_visible_from_another_tenant(
    db_session: Session, users: _Users, other_tenant_schema: str
) -> None:
    # Commit the row, so that a session that reads the wrong schema can see it.
    # The schema teardown removes it.
    with get_session_with_tenant(tenant_id=other_tenant_schema) as seed_session:
        file_id = _add_file_record(
            seed_session,
            file_metadata=build_chat_upload_metadata(
                uploaded_by_user_id=users.owner.id,
                original_content_type="image/png",
                token_count=None,
            ),
        )
        seed_session.commit()

    # The row grants access through a new session for its own tenant.
    with get_session_with_tenant(tenant_id=other_tenant_schema) as tenant_session:
        assert user_can_access_chat_file(file_id, users.owner, tenant_session)

    # The same file id and user get no access through the default tenant.
    assert not user_can_access_chat_file(file_id, users.owner, db_session)
