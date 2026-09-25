"""Unit tests for how a send's parent_message_id is resolved against the
session's mainline (the chain that follows latest_child_message_id).

The web client names the parent from the branch it shows. Its branch switches
(the message pager, a failed "Retry with" it moved past) may not have reached
the server, so an off-mainline parent in the same session is adopted. A user
message parent means a regeneration, which a client can now rule out.
"""

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from onyx.configs.constants import MessageType
from onyx.db.chat import adopt_branch_of_message
from onyx.db.models import ChatMessage
from onyx.server.query_and_chat.models import (
    AUTO_PLACE_AFTER_LATEST_MESSAGE,
    SendMessageRequest,
)
from onyx.utils.variable_functionality import global_version

SESSION_ID = uuid4()


@pytest.fixture(autouse=True)
def _restore_ee_version() -> Generator[None, None, None]:
    """Importing onyx.chat.process_message flips the EE flag; restore it."""
    original = global_version._is_ee
    yield
    global_version._is_ee = original


@dataclass
class _Msg:
    id: int
    message_type: MessageType
    parent_message_id: int | None
    latest_child_message_id: int | None = None
    preferred_response_id: int | None = None
    chat_session_id: UUID = SESSION_ID


class _Tree:
    """Messages by id, plus a db_session whose get() reads them."""

    def __init__(self, *messages: _Msg) -> None:
        self.by_id = {m.id: m for m in messages}
        self.db_session = MagicMock()
        self.db_session.get.side_effect = lambda _model, message_id: self.by_id.get(
            message_id
        )

    def mainline(self) -> list[ChatMessage]:
        """The chain below the root, as create_chat_history_chain walks it."""
        root = next(m for m in self.by_id.values() if m.parent_message_id is None)
        chain: list[ChatMessage] = []
        current = root
        while current.latest_child_message_id is not None:
            current = self.by_id[current.latest_child_message_id]
            chain.append(cast(ChatMessage, current))
        return chain

    def root(self) -> ChatMessage:
        root = next(m for m in self.by_id.values() if m.parent_message_id is None)
        return cast(ChatMessage, root)


def _failed_retry_tree() -> _Tree:
    """253 root -> 254 "Name one color." -> 255 "Blue" | 256 failed retry.

    The failed retry is the latest child, as the backend leaves it."""
    return _Tree(
        _Msg(253, MessageType.SYSTEM, None, latest_child_message_id=254),
        _Msg(254, MessageType.USER, 253, latest_child_message_id=256),
        _Msg(255, MessageType.ASSISTANT, 254),
        _Msg(256, MessageType.ASSISTANT, 254),
    )


# ---------------------------------------------------------------------------
# adopt_branch_of_message
# ---------------------------------------------------------------------------


class TestAdoptBranchOfMessage:
    def test_points_the_parent_at_an_earlier_reply(self) -> None:
        tree = _failed_retry_tree()

        assert adopt_branch_of_message(SESSION_ID, 255, tree.db_session)

        assert tree.by_id[254].latest_child_message_id == 255
        assert [m.id for m in tree.mainline()] == [254, 255]
        tree.db_session.flush.assert_called_once()
        # The caller commits it with the new message.
        tree.db_session.commit.assert_not_called()
        tree.db_session.expire.assert_called_once_with(
            tree.by_id[254], ["latest_child_message", "preferred_response"]
        )

    def test_points_every_ancestor_down_the_path(self) -> None:
        # 1 -> 2 -> {3 -> 5 -> 7, 4 (latest)}: adopting 7 moves 2's pointer.
        tree = _Tree(
            _Msg(1, MessageType.SYSTEM, None, latest_child_message_id=2),
            _Msg(2, MessageType.USER, 1, latest_child_message_id=4),
            _Msg(3, MessageType.ASSISTANT, 2, latest_child_message_id=5),
            _Msg(4, MessageType.ASSISTANT, 2),
            _Msg(5, MessageType.USER, 3, latest_child_message_id=None),
            _Msg(7, MessageType.ASSISTANT, 5),
        )

        assert adopt_branch_of_message(SESSION_ID, 7, tree.db_session)

        assert [m.id for m in tree.mainline()] == [2, 3, 5, 7]

    def test_moves_a_set_preference_with_the_latest_child(self) -> None:
        tree = _Tree(
            _Msg(196, MessageType.SYSTEM, None, latest_child_message_id=197),
            _Msg(
                197,
                MessageType.USER,
                196,
                latest_child_message_id=207,
                preferred_response_id=199,
            ),
            _Msg(198, MessageType.ASSISTANT, 197),
            _Msg(199, MessageType.ASSISTANT, 197),
            _Msg(207, MessageType.ASSISTANT, 197),
        )

        assert adopt_branch_of_message(SESSION_ID, 198, tree.db_session)

        assert tree.by_id[197].latest_child_message_id == 198
        assert tree.by_id[197].preferred_response_id == 198

    def test_leaves_an_unset_preference_unset(self) -> None:
        tree = _failed_retry_tree()

        adopt_branch_of_message(SESSION_ID, 255, tree.db_session)

        assert tree.by_id[254].preferred_response_id is None

    def test_rejects_a_message_of_another_session(self) -> None:
        tree = _failed_retry_tree()
        tree.by_id[255].chat_session_id = uuid4()

        assert not adopt_branch_of_message(SESSION_ID, 255, tree.db_session)

        assert tree.by_id[254].latest_child_message_id == 256
        tree.db_session.flush.assert_not_called()

    def test_rejects_an_unknown_message(self) -> None:
        tree = _failed_retry_tree()

        assert not adopt_branch_of_message(SESSION_ID, 999, tree.db_session)

        tree.db_session.flush.assert_not_called()

    def test_rejects_a_path_through_another_session(self) -> None:
        # 255's parent belongs to another session: nothing on the way changes.
        tree = _Tree(
            _Msg(253, MessageType.SYSTEM, None, latest_child_message_id=254),
            _Msg(254, MessageType.USER, 253, latest_child_message_id=256),
            _Msg(260, MessageType.USER, 253, chat_session_id=uuid4()),
            _Msg(255, MessageType.ASSISTANT, 260),
        )

        assert not adopt_branch_of_message(SESSION_ID, 255, tree.db_session)

        assert tree.by_id[253].latest_child_message_id == 254
        assert tree.by_id[260].latest_child_message_id is None
        tree.db_session.flush.assert_not_called()

    def test_rejects_a_path_with_a_missing_ancestor(self) -> None:
        tree = _Tree(
            _Msg(254, MessageType.USER, 900, latest_child_message_id=256),
            _Msg(255, MessageType.ASSISTANT, 254),
        )

        assert not adopt_branch_of_message(SESSION_ID, 255, tree.db_session)

        assert tree.by_id[254].latest_child_message_id == 256
        tree.db_session.flush.assert_not_called()

    def test_rejects_a_cycle(self) -> None:
        tree = _Tree(
            _Msg(254, MessageType.USER, 255, latest_child_message_id=256),
            _Msg(255, MessageType.ASSISTANT, 254),
        )

        assert not adopt_branch_of_message(SESSION_ID, 255, tree.db_session)

        assert tree.by_id[254].latest_child_message_id == 256
        tree.db_session.flush.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_parent_message
# ---------------------------------------------------------------------------


@contextmanager
def _resolving(tree: _Tree) -> Iterator[MagicMock]:
    """Patch the DB helpers _resolve_parent_message calls. Adoption runs the
    real helper against the tree; the rebuilt chain is the tree's mainline."""
    with (
        patch(
            "onyx.chat.process_message.get_or_create_root_message",
            return_value=tree.root(),
        ),
        patch(
            "onyx.chat.process_message.create_chat_history_chain",
            side_effect=lambda **_: tree.mainline(),
        ),
        patch(
            "onyx.chat.process_message.adopt_branch_of_message",
            side_effect=adopt_branch_of_message,
        ) as adopt,
    ):
        yield adopt


def _resolve(tree: _Tree, **request: Any) -> tuple[ChatMessage, list[ChatMessage]]:
    from onyx.chat.process_message import _resolve_parent_message

    return _resolve_parent_message(
        new_msg_req=SendMessageRequest(
            message="Name another color.", chat_session_id=SESSION_ID, **request
        ),
        chat_session_id=SESSION_ID,
        chat_history=tree.mainline(),
        db_session=tree.db_session,
    )


class TestResolveParentMessage:
    def test_parent_on_the_mainline_truncates_history(self) -> None:
        tree = _failed_retry_tree()
        with _resolving(tree) as adopt:
            parent, history = _resolve(tree, parent_message_id=254, regenerate=True)

        assert parent.id == 254
        assert [m.id for m in history] == [254]
        adopt.assert_not_called()

    def test_auto_place_follows_the_mainline(self) -> None:
        tree = _failed_retry_tree()
        with _resolving(tree):
            parent, history = _resolve(
                tree, parent_message_id=AUTO_PLACE_AFTER_LATEST_MESSAGE
            )

        assert parent.id == 256
        assert [m.id for m in history] == [254, 256]

    def test_adopts_an_off_mainline_parent(self) -> None:
        # F-1: the send after a failed retry names the earlier answer.
        tree = _failed_retry_tree()
        with _resolving(tree) as adopt:
            parent, history = _resolve(tree, parent_message_id=255, regenerate=False)

        assert parent.id == 255
        assert [m.id for m in history] == [254, 255]
        adopt.assert_called_once()
        assert tree.by_id[254].latest_child_message_id == 255

    def test_rejects_a_parent_outside_the_session(self) -> None:
        tree = _failed_retry_tree()
        with _resolving(tree), pytest.raises(ValueError, match="mainline"):
            _resolve(tree, parent_message_id=999, regenerate=False)

    def test_rejects_a_new_message_sent_against_a_user_message(self) -> None:
        # F-1, multi-model: the send named the owl user message, and the
        # backend regenerated the owl turn, dropping "And one about penguins."
        tree = _failed_retry_tree()
        with _resolving(tree), pytest.raises(ValueError, match="user message"):
            _resolve(tree, parent_message_id=254, regenerate=False)

    def test_legacy_request_with_a_user_parent_regenerates(self) -> None:
        tree = _failed_retry_tree()
        with _resolving(tree):
            parent, _ = _resolve(tree, parent_message_id=254)

        assert parent.message_type == MessageType.USER

    def test_rejects_a_regeneration_without_a_user_parent(self) -> None:
        # Without the check it would silently add a new user message.
        tree = _failed_retry_tree()
        with _resolving(tree), pytest.raises(ValueError, match="regeneration"):
            _resolve(tree, parent_message_id=256, regenerate=True)

    def test_legacy_request_with_an_assistant_parent_sends(self) -> None:
        tree = _failed_retry_tree()
        with _resolving(tree):
            parent, _ = _resolve(tree, parent_message_id=256)

        assert parent.message_type == MessageType.ASSISTANT

    def test_root_parent_starts_over(self) -> None:
        tree = _failed_retry_tree()
        with _resolving(tree):
            parent, history = _resolve(tree, parent_message_id=None, regenerate=False)

        assert parent.id == 253
        assert history == []
