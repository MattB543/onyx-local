"""Tests for CRM tool streaming packet emissions and session replay helpers."""

from queue import Queue
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from onyx.chat.emitter import Emitter
from onyx.configs.constants import FileOrigin
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.session_loading import create_crm_create_packets
from onyx.server.query_and_chat.session_loading import (
    create_crm_log_interaction_packets,
)
from onyx.server.query_and_chat.session_loading import create_crm_search_packets
from onyx.server.query_and_chat.session_loading import create_crm_update_packets
from onyx.server.query_and_chat.streaming_models import CrmCreateToolDelta
from onyx.server.query_and_chat.streaming_models import CrmCreateToolStart
from onyx.server.query_and_chat.streaming_models import CrmLogInteractionToolDelta
from onyx.server.query_and_chat.streaming_models import CrmLogInteractionToolStart
from onyx.server.query_and_chat.streaming_models import CrmSearchToolDelta
from onyx.server.query_and_chat.streaming_models import CrmSearchToolStart
from onyx.server.query_and_chat.streaming_models import CrmUpdateToolDelta
from onyx.server.query_and_chat.streaming_models import CrmUpdateToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.db.enums import CrmInteractionType
from onyx.db.models import CrmContact
from onyx.db.models import CrmInteraction
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES
from onyx.tools.tool_implementations.crm.crm_create_tool import CrmCreateTool
from onyx.tools.tool_implementations.crm.crm_log_interaction_tool import (
    CrmLogInteractionTool,
)
from onyx.tools.tool_implementations.crm.models import serialize_contact
from onyx.tools.tool_implementations.crm.crm_search_tool import CrmSearchTool
from onyx.tools.tool_implementations.crm.crm_update_tool import CrmUpdateTool
from onyx.tools.models import ToolCallException


class _TestBus:
    """Unwraps ``(model_idx, packet)`` tuples from the Emitter merge queue.

    Upstream #9803 (merge-queue) changed Emitter to put tuples on the queue;
    our tests want to read the original Packet directly.
    """

    def __init__(self, queue: Queue) -> None:
        self._queue = queue

    def get_nowait(self) -> Any:
        item = self._queue.get_nowait()
        if isinstance(item, tuple) and len(item) == 2:
            return item[1]
        return item


class _TestEmitter(Emitter):
    def __init__(self) -> None:
        queue: Queue = Queue()
        super().__init__(queue)
        self.bus: _TestBus = _TestBus(queue)


@pytest.fixture
def emitter() -> Emitter:
    return _TestEmitter()


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def patch_stage_options(monkeypatch: pytest.MonkeyPatch) -> None:
    default_stages = ["lead", "active", "inactive", "archived"]
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.crm.crm_create_tool.get_allowed_contact_stages",
        lambda _db_session: default_stages,
    )
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.crm.crm_update_tool.get_allowed_contact_stages",
        lambda _db_session: default_stages,
    )


@pytest.fixture
def placement() -> Placement:
    return Placement(turn_index=0, tab_index=0)


class TestCrmToolEmitStart:
    def test_crm_search_emit_start(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmSearchTool(tool_id=1, db_session=db_session, emitter=emitter)
        tool.emit_start(placement)

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmSearchToolStart)
        assert packet.placement.turn_index == placement.turn_index
        assert packet.placement.tab_index == placement.tab_index

    def test_crm_create_emit_start(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmCreateTool(
            tool_id=2,
            db_session=db_session,
            emitter=emitter,
            user_id=str(uuid4()),
        )
        tool.emit_start(placement)

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmCreateToolStart)
        assert packet.placement.turn_index == placement.turn_index
        assert packet.placement.tab_index == placement.tab_index

    def test_crm_update_emit_start(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)
        tool.emit_start(placement)

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmUpdateToolStart)
        assert packet.placement.turn_index == placement.turn_index
        assert packet.placement.tab_index == placement.tab_index

    def test_crm_log_interaction_emit_start(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmLogInteractionTool(
            tool_id=4,
            db_session=db_session,
            emitter=emitter,
            user_id=str(uuid4()),
        )
        tool.emit_start(placement)

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmLogInteractionToolStart)
        assert packet.placement.turn_index == placement.turn_index
        assert packet.placement.tab_index == placement.tab_index


class TestCrmToolRun:
    @pytest.mark.parametrize(
        "tool_cls",
        [CrmSearchTool, CrmCreateTool, CrmUpdateTool, CrmLogInteractionTool],
    )
    def test_is_available_false_when_crm_tables_missing(self, db_session, tool_cls) -> None:
        assert tool_cls.is_available(db_session) is False

    def test_crm_search_run_emits_delta(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmSearchTool(tool_id=1, db_session=db_session, emitter=emitter)

        with patch(
            "onyx.tools.tool_implementations.crm.crm_search_tool.search_crm_entities"
        ) as mock_search:
            mock_search.return_value = ([], 0)

            result = tool.run(
                placement=placement,
                query="acme",
                entity_types=["contact"],
                page_num=0,
                page_size=10,
            )

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmSearchToolDelta)
        assert packet.obj.payload["status"] == "ok"
        assert '"status": "ok"' in result.llm_facing_response

    def test_crm_search_is_marked_citeable(self) -> None:
        assert CrmSearchTool.NAME in CITEABLE_TOOLS_NAMES

    def test_crm_create_run_emits_delta(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmCreateTool(
            tool_id=2,
            db_session=db_session,
            emitter=emitter,
            user_id=str(uuid4()),
        )

        with patch.object(tool, "_create_contact") as mock_create_contact:
            mock_create_contact.return_value = {
                "status": "created",
                "entity_type": "contact",
                "contact": {"id": str(uuid4()), "first_name": "Alice"},
            }

            result = tool.run(
                placement=placement,
                entity_type="contact",
                contact={"first_name": "Alice"},
            )

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmCreateToolDelta)
        assert packet.obj.payload["status"] == "created"
        assert '"entity_type": "contact"' in result.llm_facing_response

    def test_crm_create_tool_definition_exposes_profile_picture_url(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmCreateTool(
            tool_id=2,
            db_session=db_session,
            emitter=emitter,
            user_id=str(uuid4()),
        )

        definition = tool.tool_definition()
        contact_properties = definition["function"]["parameters"]["properties"][
            "contact"
        ]["properties"]

        assert "profile_picture_url" in contact_properties

    def test_crm_create_contact_profile_picture_download_failure_is_non_fatal(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmCreateTool(
            tool_id=2,
            db_session=db_session,
            emitter=emitter,
            user_id=str(uuid4()),
        )
        contact = CrmContact(first_name="Alice", status="lead")
        contact.id = uuid4()
        mocked_db_session = MagicMock()

        with (
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.create_contact",
                return_value=(contact, True),
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.get_contact_tags",
                return_value=[],
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.get_contact_owner_ids",
                return_value=[],
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.save_file_from_url",
                side_effect=Exception("boom"),
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.update_contact"
            ) as mock_update_contact,
        ):
            payload = tool._create_contact(
                db_session=mocked_db_session,
                contact_data={
                    "first_name": "Alice",
                    "owner_ids": [],
                    "profile_picture_url": "https://example.com/avatar.png",
                },
            )

        assert payload["status"] == "created"
        assert payload["contact"]["profile_picture_file_id"] is None
        mock_update_contact.assert_not_called()

    def test_crm_create_contact_downloads_profile_picture_when_created(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmCreateTool(
            tool_id=2,
            db_session=db_session,
            emitter=emitter,
            user_id=str(uuid4()),
        )
        db_session_mock = MagicMock()
        contact = CrmContact(first_name="Alice", status="lead")
        contact.id = uuid4()
        updated_contact = CrmContact(
            first_name="Alice",
            status="lead",
            profile_picture_file_id="file-123",
        )
        updated_contact.id = contact.id

        with (
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.create_contact",
                return_value=(contact, True),
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.get_contact_tags",
                return_value=[],
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.get_contact_owner_ids",
                return_value=[],
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.save_file_from_url",
                return_value="file-123",
            ) as mock_save_file,
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.update_contact",
                return_value=(updated_contact, True),
            ) as mock_update_contact,
        ):
            payload = tool._create_contact(
                db_session=db_session_mock,
                contact_data={
                    "first_name": "Alice",
                    "owner_ids": [],
                    "profile_picture_url": "https://example.com/avatar.png",
                },
            )

        mock_save_file.assert_called_once_with(
            "https://example.com/avatar.png",
            display_name=f"crm_profile_{contact.id}",
            file_origin=FileOrigin.CRM_UPLOAD,
            require_image=True,
        )
        mock_update_contact.assert_called_once_with(
            db_session=db_session_mock,
            contact=contact,
            patches={"profile_picture_file_id": "file-123"},
        )
        assert payload["contact"]["profile_picture_file_id"] == "file-123"

    def test_crm_create_contact_existing_contact_does_not_download_profile_picture(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmCreateTool(
            tool_id=2,
            db_session=db_session,
            emitter=emitter,
            user_id=str(uuid4()),
        )
        contact = CrmContact(first_name="Alice", status="lead")
        contact.id = uuid4()

        with (
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.create_contact",
                return_value=(contact, False),
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.get_contact_tags",
                return_value=[],
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.get_contact_owner_ids",
                return_value=[],
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.save_file_from_url"
            ) as mock_save_file,
            patch(
                "onyx.tools.tool_implementations.crm.crm_create_tool.update_contact"
            ) as mock_update_contact,
        ):
            payload = tool._create_contact(
                db_session=MagicMock(),
                contact_data={
                    "first_name": "Alice",
                    "owner_ids": [],
                    "profile_picture_url": "https://example.com/avatar.png",
                },
            )

        assert payload["status"] == "already_exists"
        mock_save_file.assert_not_called()
        mock_update_contact.assert_not_called()

    def test_crm_update_run_emits_delta(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)
        contact_id = uuid4()
        contact = CrmContact(
            first_name="Alice",
            status="lead",
        )
        contact.id = contact_id
        updated_contact = CrmContact(
            first_name="Alicia",
            status="active",
        )
        updated_contact.id = contact_id

        with (
            patch(
                "onyx.tools.tool_implementations.crm.crm_update_tool.get_contact_by_id"
            ) as mock_get_contact,
            patch(
                "onyx.tools.tool_implementations.crm.crm_update_tool.update_contact"
            ) as mock_update_contact,
            patch(
                "onyx.tools.tool_implementations.crm.crm_update_tool.get_contact_owner_ids"
            ) as mock_get_contact_owner_ids,
            patch(
                "onyx.tools.tool_implementations.crm.crm_update_tool.get_contact_tags"
            ) as mock_get_tags,
        ):
            mock_get_contact.return_value = contact
            mock_update_contact.return_value = (updated_contact, True)
            mock_get_contact_owner_ids.return_value = []
            mock_get_tags.return_value = []

            result = tool.run(
                placement=placement,
                entity_type="contact",
                entity_id=str(contact_id),
                updates={"first_name": "Alicia", "status": "active"},
            )

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmUpdateToolDelta)
        assert packet.obj.payload["status"] == "updated"
        assert '"status": "updated"' in result.llm_facing_response

    def test_crm_update_normalize_contact_updates_downloads_profile_picture(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)

        with patch(
            "onyx.tools.tool_implementations.crm.crm_update_tool.save_file_from_url",
            return_value="file-123",
        ) as mock_save_file:
            updates = tool._normalize_contact_updates(
                {"profile_picture_url": "https://example.com/avatar.png"}
            )

        mock_save_file.assert_called_once_with(
            "https://example.com/avatar.png",
            display_name="crm_profile_picture",
            file_origin=FileOrigin.CRM_UPLOAD,
            require_image=True,
        )
        assert updates["profile_picture_file_id"] == "file-123"
        assert "profile_picture_url" not in updates

    def test_crm_update_normalize_contact_updates_clears_profile_picture(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)

        updates = tool._normalize_contact_updates({"profile_picture_url": None})

        assert updates["profile_picture_file_id"] is None

    def test_crm_update_normalize_contact_updates_empty_string_clears_profile_picture(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)

        updates = tool._normalize_contact_updates({"profile_picture_url": ""})

        assert updates["profile_picture_file_id"] is None
        assert "profile_picture_url" not in updates

    def test_crm_update_normalize_contact_updates_rejects_invalid_profile_picture_type(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)

        with pytest.raises(ToolCallException) as exc:
            tool._normalize_contact_updates({"profile_picture_url": 123})

        assert "string URL or null" in exc.value.llm_facing_message

    def test_crm_update_normalize_contact_updates_profile_picture_download_failure_is_non_fatal(
        self, emitter: Emitter, db_session
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)

        with patch(
            "onyx.tools.tool_implementations.crm.crm_update_tool.save_file_from_url",
            side_effect=Exception("boom"),
        ):
            updates = tool._normalize_contact_updates(
                {
                    "first_name": "Alice",
                    "profile_picture_url": "https://example.com/avatar.png",
                }
            )

        assert updates["first_name"] == "Alice"
        assert "profile_picture_file_id" not in updates

    def test_serialize_contact_profile_picture_none(self) -> None:
        contact = CrmContact(
            first_name="Bob",
            status="lead",
        )
        contact.id = uuid4()

        payload = serialize_contact(contact, owner_ids=[], tags=[])

        assert payload["profile_picture_file_id"] is None
        assert payload["profile_picture_url"] is None

    def test_serialize_contact_includes_profile_picture_fields(self) -> None:
        contact = CrmContact(
            first_name="Alice",
            status="lead",
            profile_picture_file_id="file-123",
        )
        contact.id = uuid4()

        payload = serialize_contact(contact, owner_ids=[], tags=[])

        assert payload["profile_picture_file_id"] == "file-123"
        assert payload["profile_picture_url"] == "/api/chat/file/file-123"

    def test_crm_log_interaction_run_emits_delta(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmLogInteractionTool(
            tool_id=4,
            db_session=db_session,
            emitter=emitter,
            user_id=str(uuid4()),
        )
        interaction = CrmInteraction(
            type=CrmInteractionType.CALL,
            title="Call with Acme",
        )
        interaction.id = uuid4()

        with (
            patch(
                "onyx.tools.tool_implementations.crm.crm_log_interaction_tool.create_interaction"
            ) as mock_create_interaction,
            patch(
                "onyx.tools.tool_implementations.crm.crm_log_interaction_tool.add_interaction_attendees"
            ),
            patch(
                "onyx.tools.tool_implementations.crm.crm_log_interaction_tool.get_interaction_attendees"
            ) as mock_get_attendees,
        ):
            mock_create_interaction.return_value = interaction
            mock_get_attendees.return_value = []

            result = tool.run(
                placement=placement,
                title="Call with Acme",
                interaction_type="call",
                summary="Discussed next steps",
            )

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmLogInteractionToolDelta)
        assert packet.obj.payload["status"] == "created"
        assert "updated_at" in packet.obj.payload["interaction"]
        assert '"status": "created"' in result.llm_facing_response


class TestCrmSessionReplayPacketBuilders:
    def test_create_crm_search_packets(self) -> None:
        packets = create_crm_search_packets(
            tool_call_response='{"status":"ok","results":[{"id":"1"}]}',
            turn_index=1,
            tab_index=0,
        )

        assert len(packets) == 3
        assert isinstance(packets[0].obj, CrmSearchToolStart)
        assert isinstance(packets[1].obj, CrmSearchToolDelta)
        assert isinstance(packets[2].obj, SectionEnd)
        assert packets[1].obj.payload["status"] == "ok"

    def test_create_crm_create_packets(self) -> None:
        packets = create_crm_create_packets(
            tool_call_response='{"status":"created","entity_type":"contact"}',
            turn_index=2,
            tab_index=1,
        )

        assert len(packets) == 3
        assert isinstance(packets[0].obj, CrmCreateToolStart)
        assert isinstance(packets[1].obj, CrmCreateToolDelta)
        assert isinstance(packets[2].obj, SectionEnd)
        assert packets[1].obj.payload["entity_type"] == "contact"

    def test_create_crm_update_packets(self) -> None:
        packets = create_crm_update_packets(
            tool_call_response='{"status":"updated","entity_type":"organization"}',
            turn_index=3,
            tab_index=0,
        )

        assert len(packets) == 3
        assert isinstance(packets[0].obj, CrmUpdateToolStart)
        assert isinstance(packets[1].obj, CrmUpdateToolDelta)
        assert isinstance(packets[2].obj, SectionEnd)
        assert packets[1].obj.payload["status"] == "updated"

    def test_create_crm_log_interaction_packets(self) -> None:
        packets = create_crm_log_interaction_packets(
            tool_call_response='{"status":"created","interaction":{"title":"Call"}}',
            turn_index=4,
            tab_index=0,
        )

        assert len(packets) == 3
        assert isinstance(packets[0].obj, CrmLogInteractionToolStart)
        assert isinstance(packets[1].obj, CrmLogInteractionToolDelta)
        assert isinstance(packets[2].obj, SectionEnd)
        interaction = packets[1].obj.payload["interaction"]
        assert isinstance(interaction, dict)
        assert interaction["title"] == "Call"
