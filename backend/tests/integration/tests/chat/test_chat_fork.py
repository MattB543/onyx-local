"""Integration tests for "Branch from here" (POST /chat/fork-chat-session)."""

from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_file_utils import build_chat_upload_metadata
from onyx.chat.chat_processing_checker import set_processing_status
from onyx.configs.constants import DocumentSource, FileOrigin, MessageType
from onyx.db.chat import add_search_docs_to_chat_message, add_search_docs_to_tool_call
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ChatSessionSharedStatus, IncognitoRecordMode
from onyx.db.models import (
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatSession,
    SearchDoc,
    Tool,
    ToolCall,
    ToolCall__SearchDoc,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.tools.constants import SEARCH_TOOL_ID
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import (
    DATestChatSession,
    DATestLLMProvider,
    DATestUser,
)

Q1, A1, Q2, A2 = "First question", "First answer", "Second question", "Second answer"

# Per-row ids that legitimately differ between a session and its branch.
_PACKET_ROW_KEYS = {"db_doc_id"}


@pytest.fixture(scope="module", autouse=True)
def reset_for_module() -> None:
    reset_all()


def _send(
    session: DATestChatSession, message: str, user: DATestUser, reply: str
) -> None:
    response = ChatSessionManager.send_message(
        chat_session_id=session.id,
        message=message,
        user_performing_action=user,
        mock_llm_response=reply,
    )
    assert response.error is None, response.error


def _detail(session: DATestChatSession, user: DATestUser) -> dict[str, Any]:
    return ChatSessionManager.get_chat_session_detail(
        chat_session=session, user_performing_action=user
    )


def _messages(session: DATestChatSession, user: DATestUser) -> list[dict[str, Any]]:
    """The active chain (root's latest_child links), oldest first, without the
    SYSTEM root. Off-chain rows such as summaries and siblings are excluded."""
    all_messages = _detail(session, user)["messages"]
    by_id = {m["message_id"]: m for m in all_messages}
    current = next(m for m in all_messages if m["parent_message"] is None)
    chain: list[dict[str, Any]] = []
    while current["latest_child_message"] is not None:
        current = by_id[current["latest_child_message"]]
        chain.append(current)
    return chain


def _two_turn_session(
    user: DATestUser, description: str = "Source chat"
) -> tuple[DATestChatSession, list[dict[str, Any]]]:
    session = ChatSessionManager.create(
        user_performing_action=user, description=description
    )
    _send(session, Q1, user, A1)
    _send(session, Q2, user, A2)
    messages = _messages(session, user)
    assert [m["message"] for m in messages] == [Q1, A1, Q2, A2]
    return session, messages


def _assert_chain(messages: list[dict[str, Any]]) -> None:
    for previous, current in zip(messages, messages[1:], strict=False):
        assert current["parent_message"] == previous["message_id"]


def test_fork_at_user_message_prefills_and_continues(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)

    branch, body = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[2]["message_id"],  # Q2
        user_performing_action=basic_user,
    )
    assert body["prefill_message"] == Q2
    assert body["prefill_files"] == []
    assert body["prefill_skipped_file_count"] == 0

    branch_messages = _messages(branch, basic_user)
    assert [m["message"] for m in branch_messages] == [Q1, A1]
    _assert_chain(branch_messages)

    _send(branch, body["prefill_message"], basic_user, "Fresh answer")
    branch_messages = _messages(branch, basic_user)
    assert [m["message"] for m in branch_messages] == [Q1, A1, Q2, "Fresh answer"]
    _assert_chain(branch_messages)
    assert all(m["chat_session_id"] == str(branch.id) for m in branch_messages)

    # The source is untouched, ids included.
    assert _messages(source, basic_user) == source_messages


def test_fork_at_assistant_message_and_continue(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)

    branch, body = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[1]["message_id"],  # A1
        user_performing_action=basic_user,
    )
    assert body["prefill_message"] is None

    detail = _detail(branch, basic_user)
    assert detail["forked_from_chat_session_id"] == str(source.id)
    assert detail["forked_from_description"] == source.description

    branch_messages = _messages(branch, basic_user)
    assert [m["message"] for m in branch_messages] == [Q1, A1]
    _assert_chain(branch_messages)
    source_ids = {m["message_id"] for m in source_messages}
    assert not source_ids & {m["message_id"] for m in branch_messages}

    _send(branch, "Follow-up", basic_user, "Follow-up answer")
    assert [m["message"] for m in _messages(branch, basic_user)] == [
        Q1,
        A1,
        "Follow-up",
        "Follow-up answer",
    ]
    assert _messages(source, basic_user) == source_messages


def test_fork_at_first_user_message(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)

    branch, body = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[0]["message_id"],  # Q1
        user_performing_action=basic_user,
    )
    assert body["prefill_message"] == Q1
    assert _messages(branch, basic_user) == []

    _send(branch, Q1, basic_user, "Another first answer")
    assert [m["message"] for m in _messages(branch, basic_user)] == [
        Q1,
        "Another first answer",
    ]


def _seed_search_tool_call(
    session_id: UUID, assistant_message_id: int, document_id: str
) -> None:
    """Attach a SearchTool call with one doc to an assistant message, linking
    the doc to both the tool call and the message like save_chat does. Replay
    builds search packets from the arguments and the linked docs."""
    with get_session_with_current_tenant() as db_session:
        tool_id = db_session.scalars(
            select(Tool.id).where(Tool.in_code_tool_id == SEARCH_TOOL_ID)
        ).first()
        assert tool_id is not None, "SearchTool is not seeded"
        doc = SearchDoc(
            document_id=document_id,
            chunk_ind=0,
            semantic_id="Doc",
            link="https://example.com/doc",
            blurb="blurb",
            source_type=DocumentSource.WEB,
            boost=0,
            hidden=False,
            doc_metadata={},
            score=1.0,
            match_highlights=[],
        )
        db_session.add(doc)
        db_session.flush()
        tool_call = ToolCall(
            chat_session_id=session_id,
            parent_chat_message_id=assistant_message_id,
            turn_number=0,
            tab_index=0,
            tool_id=tool_id,
            tool_call_id="call_1",
            tool_call_arguments={"queries": ["first question"]},
            tool_call_response="Doc: blurb",
            tool_call_tokens=3,
        )
        db_session.add(tool_call)
        db_session.flush()
        add_search_docs_to_tool_call(tool_call.id, [doc.id], db_session)
        add_search_docs_to_chat_message(assistant_message_id, [doc.id], db_session)
        message = db_session.get(ChatMessage, assistant_message_id)
        assert message is not None
        message.citations = {1: doc.id}
        db_session.commit()


def _tool_calls_for_session(session_id: UUID) -> list[dict[str, Any]]:
    with get_session_with_current_tenant() as db_session:
        rows = db_session.scalars(
            select(ToolCall).where(ToolCall.chat_session_id == session_id)
        ).all()
        out = []
        for tc in rows:
            tool_doc_ids = set(
                db_session.scalars(
                    select(ToolCall__SearchDoc.search_doc_id).where(
                        ToolCall__SearchDoc.tool_call_id == tc.id
                    )
                ).all()
            )
            message_doc_ids = set(
                db_session.scalars(
                    select(ChatMessage__SearchDoc.search_doc_id).where(
                        ChatMessage__SearchDoc.chat_message_id
                        == tc.parent_chat_message_id
                    )
                ).all()
            )
            out.append(
                {
                    "arguments": tc.tool_call_arguments,
                    "response": tc.tool_call_response,
                    "tool_doc_ids": tool_doc_ids,
                    "message_doc_ids": message_doc_ids,
                }
            )
        return out


def _strip_row_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip_row_ids(v) for k, v in value.items() if k not in _PACKET_ROW_KEYS
        }
    if isinstance(value, list):
        return [_strip_row_ids(v) for v in value]
    return value


def _normalized_packets(detail: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return _strip_row_ids(detail["packets"])


def test_rich_replay_survives_fork_and_source_delete(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)
    _seed_search_tool_call(source.id, source_messages[1]["message_id"], "doc-1")
    source_tool_calls = _tool_calls_for_session(source.id)
    assert len(source_tool_calls) == 1
    source_packets = _normalized_packets(_detail(source, basic_user))
    packet_types = {p["obj"]["type"] for turn in source_packets for p in turn}
    assert "search_tool_start" in packet_types, packet_types

    branch, _ = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[3]["message_id"],  # A2: copies A1's tool call
        user_performing_action=basic_user,
    )

    def check_branch() -> None:
        detail = _detail(branch, basic_user)
        assistant = next(m for m in detail["messages"] if m["message"] == A1)
        assert [d["document_id"] for d in assistant["context_docs"]] == ["doc-1"]
        assert assistant["citations"] == {"1": "doc-1"}
        assert _normalized_packets(detail) == source_packets

        branch_tool_calls = _tool_calls_for_session(branch.id)
        assert len(branch_tool_calls) == 1
        assert branch_tool_calls[0]["arguments"] == source_tool_calls[0]["arguments"]
        assert branch_tool_calls[0]["response"] == source_tool_calls[0]["response"]
        # Cloned doc, not shared: linked to both the tool call and the message.
        assert branch_tool_calls[0]["tool_doc_ids"]
        assert (
            not branch_tool_calls[0]["tool_doc_ids"]
            & (source_tool_calls[0]["tool_doc_ids"])
        )
        assert (
            branch_tool_calls[0]["tool_doc_ids"]
            <= branch_tool_calls[0]["message_doc_ids"]
        )

    check_branch()
    assert ChatSessionManager.delete(
        chat_session=source, user_performing_action=basic_user
    )
    check_branch()

    # The copied tool history does not break a further turn.
    _send(branch, "Follow-up", basic_user, "Follow-up answer")
    assert [m["message"] for m in _messages(branch, basic_user)] == [
        Q1,
        A1,
        Q2,
        A2,
        "Follow-up",
        "Follow-up answer",
    ]


def test_independence_on_delete(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)
    branch, _ = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[3]["message_id"],
        user_performing_action=basic_user,
    )
    assert ChatSessionManager.delete(
        chat_session=source, user_performing_action=basic_user
    )
    detail = _detail(branch, basic_user)
    assert detail["forked_from_chat_session_id"] is None
    assert detail["forked_from_description"] is None
    assert [m["message"] for m in _messages(branch, basic_user)] == [Q1, A1, Q2, A2]

    source2, source2_messages = _two_turn_session(basic_user)
    branch2, _ = ChatSessionManager.fork(
        chat_session=source2,
        message_id=source2_messages[3]["message_id"],
        user_performing_action=basic_user,
    )
    assert ChatSessionManager.delete(
        chat_session=branch2, user_performing_action=basic_user
    )
    assert _messages(source2, basic_user) == source2_messages


def _seed_raw_chat_file(content: bytes, owner: DATestUser) -> FileDescriptor:
    """A chat upload without a UserFile row (the pre-projects upload shape),
    stamped with the owner metadata `verify_user_files` requires."""
    file_id = str(uuid4())
    get_default_file_store().save_file(
        content=BytesIO(content),
        display_name="notes.txt",
        file_origin=FileOrigin.CHAT_UPLOAD,
        file_type="text/plain",
        file_metadata=build_chat_upload_metadata(
            uploaded_by_user_id=UUID(owner.id),
            original_content_type="text/plain",
            token_count=None,
        ),
        file_id=file_id,
    )
    return {"id": file_id, "type": ChatFileType.PLAIN_TEXT, "name": "notes.txt"}


def test_raw_files_are_copied(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    descriptor = _seed_raw_chat_file(b"hello branch", basic_user)
    source = ChatSessionManager.create(user_performing_action=basic_user)
    response = ChatSessionManager.send_message(
        chat_session_id=source.id,
        message="Read the attachment",
        user_performing_action=basic_user,
        file_descriptors=[descriptor],
        mock_llm_response="Read it",
    )
    assert response.error is None, response.error
    source_messages = _messages(source, basic_user)
    assert source_messages[0]["files"][0]["id"] == descriptor["id"]

    branch, _ = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[1]["message_id"],
        user_performing_action=basic_user,
    )
    copied_id = _messages(branch, basic_user)[0]["files"][0]["id"]
    assert copied_id != descriptor["id"]
    for file_id in (descriptor["id"], copied_id):
        assert FileManager.fetch_uploaded_file(file_id, basic_user) == b"hello branch"

    # A raw attachment on the fork point itself is not carried into the prefill:
    # nothing in the branch would own the copy.
    prefill_branch, body = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[0]["message_id"],
        user_performing_action=basic_user,
    )
    assert _messages(prefill_branch, basic_user) == []
    assert body["prefill_message"] == "Read the attachment"
    assert body["prefill_files"] == []
    assert body["prefill_skipped_file_count"] == 1

    assert ChatSessionManager.delete(
        chat_session=source, user_performing_action=basic_user
    )
    assert FileManager.fetch_uploaded_file(copied_id, basic_user) == b"hello branch"


def test_user_file_attachments_are_shared_and_prefilled(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    descriptors, error = FileManager.upload_files(
        files=[("shared.txt", BytesIO(b"shared bytes"))],
        user_performing_action=basic_user,
    )
    assert not error, error
    descriptor = descriptors[0]
    assert descriptor.get("user_file_id")

    source = ChatSessionManager.create(user_performing_action=basic_user)
    response = ChatSessionManager.send_message(
        chat_session_id=source.id,
        message="Read the shared attachment",
        user_performing_action=basic_user,
        file_descriptors=[descriptor],
        mock_llm_response="Read it",
    )
    assert response.error is None, response.error
    source_messages = _messages(source, basic_user)

    # Forking after the attachment keeps the UserFile-backed descriptor as is.
    branch, _ = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[1]["message_id"],
        user_performing_action=basic_user,
    )
    copied = _messages(branch, basic_user)[0]["files"][0]
    assert copied["id"] == descriptor["id"]
    assert copied["user_file_id"] == descriptor["user_file_id"]

    # Forking at the user message returns it for re-attachment, uncopied.
    _, body = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[0]["message_id"],
        user_performing_action=basic_user,
    )
    assert body["prefill_message"] == "Read the shared attachment"
    assert body["prefill_skipped_file_count"] == 0
    assert len(body["prefill_files"]) == 1
    assert body["prefill_files"][0]["id"] == descriptor["id"]
    assert body["prefill_files"][0]["user_file_id"] == descriptor["user_file_id"]
    assert FileManager.fetch_uploaded_file(descriptor["id"], basic_user) == (
        b"shared bytes"
    )


def test_active_run_refuses_owner_and_hides_from_others(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)
    other_user = UserManager.create(name="fork_active_run_user")
    a1_id = source_messages[1]["message_id"]
    cache = get_cache_backend(tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)

    set_processing_status(source.id, cache, True, run_id=a1_id)
    try:
        # Ownership is checked before the run state, so a non-owner cannot
        # tell an active private session from a missing one.
        assert (
            ChatSessionManager.fork_expect_error(
                chat_session_id=source.id,
                message_id=a1_id,
                user_performing_action=other_user,
            )
            == 404
        )
        assert (
            ChatSessionManager.fork_expect_error(
                chat_session_id=source.id,
                message_id=a1_id,
                user_performing_action=basic_user,
            )
            == 409
        )
    finally:
        set_processing_status(source.id, cache, False)

    branch, _ = ChatSessionManager.fork(
        chat_session=source, message_id=a1_id, user_performing_action=basic_user
    )
    assert [m["message"] for m in _messages(branch, basic_user)] == [Q1, A1]


def _seed_summary(session_id: UUID, parent_id: int, last_summarized_id: int) -> int:
    with get_session_with_current_tenant() as db_session:
        summary = ChatMessage(
            chat_session_id=session_id,
            parent_message_id=parent_id,
            last_summarized_message_id=last_summarized_id,
            message_type=MessageType.ASSISTANT,
            message="Summary of the first turn",
            token_count=5,
        )
        db_session.add(summary)
        db_session.commit()
        return summary.id


def _summaries(session_id: UUID) -> list[ChatMessage]:
    with get_session_with_current_tenant() as db_session:
        db_session.expire_on_commit = False
        return list(
            db_session.scalars(
                select(ChatMessage).where(
                    ChatMessage.chat_session_id == session_id,
                    ChatMessage.last_summarized_message_id.isnot(None),
                )
            ).all()
        )


def test_summary_is_carried(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)
    q2_id, a1_id, a2_id = (
        source_messages[2]["message_id"],
        source_messages[1]["message_id"],
        source_messages[3]["message_id"],
    )
    summary_id = _seed_summary(source.id, parent_id=q2_id, last_summarized_id=a1_id)

    branch, _ = ChatSessionManager.fork(
        chat_session=source, message_id=a2_id, user_performing_action=basic_user
    )
    branch_messages = {m["message"]: m for m in _messages(branch, basic_user)}
    summaries = _summaries(branch.id)
    assert len(summaries) == 1
    assert summaries[0].parent_message_id == branch_messages[Q2]["message_id"]
    assert summaries[0].last_summarized_message_id == branch_messages[A1]["message_id"]
    # The chain itself does not include the summary.
    assert [m["message"] for m in _messages(branch, basic_user)] == [Q1, A1, Q2, A2]

    assert (
        ChatSessionManager.fork_expect_error(
            chat_session_id=source.id,
            message_id=summary_id,
            user_performing_action=basic_user,
        )
        == 400
    )


def _set_incognito(session_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(incognito_record_mode=IncognitoRecordMode.FULL_HISTORY)
        )
        db_session.commit()


def _share_publicly(session: DATestChatSession, user: DATestUser) -> None:
    response = client.patch(
        f"{API_SERVER_URL}/chat/chat-session/{session.id}",
        json={"sharing_status": ChatSessionSharedStatus.PUBLIC.value},
        headers=user.headers,
    )
    response.raise_for_status()


def test_permissions_and_refusals(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)
    other_source, other_messages = _two_turn_session(basic_user)
    other_user = UserManager.create(name="fork_other_user")
    a1_id = source_messages[1]["message_id"]

    def status(session_id: UUID, message_id: int, user: DATestUser) -> int:
        return ChatSessionManager.fork_expect_error(
            chat_session_id=session_id,
            message_id=message_id,
            user_performing_action=user,
        )

    assert status(source.id, a1_id, other_user) == 404
    assert status(uuid4(), a1_id, basic_user) == 404
    assert status(source.id, other_messages[1]["message_id"], basic_user) == 400
    assert status(source.id, 10**9, basic_user) == 400

    _set_incognito(other_source.id)
    assert status(other_source.id, other_messages[1]["message_id"], basic_user) == 400

    branch, _ = ChatSessionManager.fork(
        chat_session=source, message_id=a1_id, user_performing_action=basic_user
    )
    _share_publicly(branch, basic_user)
    shared_view = ChatSessionManager.get_chat_session_detail(
        chat_session=branch, user_performing_action=other_user, is_shared=True
    )
    assert shared_view["forked_from_chat_session_id"] is None
    assert shared_view["forked_from_description"] is None
    assert _detail(branch, basic_user)["forked_from_chat_session_id"] == str(source.id)


def _seed_second_model_response(session_id: UUID, user_message_id: int) -> int:
    """Turn the last turn into a 2-model turn: a sibling assistant row becomes
    the latest child while the original stays the preferred response."""
    with get_session_with_current_tenant() as db_session:
        user_message = db_session.get(ChatMessage, user_message_id)
        assert user_message is not None
        preferred_id = user_message.latest_child_message_id
        assert preferred_id is not None
        sibling = ChatMessage(
            chat_session_id=session_id,
            parent_message_id=user_message_id,
            message_type=MessageType.ASSISTANT,
            message="Second model answer",
            token_count=3,
            model_display_name="model-b",
        )
        db_session.add(sibling)
        db_session.flush()
        user_message.preferred_response_id = preferred_id
        user_message.latest_child_message_id = sibling.id
        db_session.commit()
        return sibling.id


def test_multi_model_fork_keeps_one_child(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user)
    sibling_id = _seed_second_model_response(
        source.id, source_messages[2]["message_id"]
    )

    branch, _ = ChatSessionManager.fork(
        chat_session=source, message_id=sibling_id, user_performing_action=basic_user
    )
    branch_messages = _messages(branch, basic_user)
    assert [m["message"] for m in branch_messages] == [
        Q1,
        A1,
        Q2,
        "Second model answer",
    ]
    copied_q2, copied_answer = branch_messages[2], branch_messages[3]
    children = [
        m
        for m in _detail(branch, basic_user)["messages"]
        if m["parent_message"] == copied_q2["message_id"]
    ]
    assert len(children) == 1
    assert copied_q2["preferred_response_id"] == copied_answer["message_id"]
    assert copied_answer["model_display_name"] == "model-b"


def test_branch_title(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    source, source_messages = _two_turn_session(basic_user, description="Roadmap")
    branch, _ = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[1]["message_id"],
        user_performing_action=basic_user,
    )
    assert _detail(branch, basic_user)["description"] == "Branch of Roadmap"

    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            update(ChatSession)
            .where(ChatSession.id == source.id)
            .values(description=None)
        )
        db_session.commit()
    untitled_branch, _ = ChatSessionManager.fork(
        chat_session=source,
        message_id=source_messages[1]["message_id"],
        user_performing_action=basic_user,
    )
    assert _detail(untitled_branch, basic_user)["description"] == "Branch of New Chat"
