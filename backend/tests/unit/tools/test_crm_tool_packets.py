"""Tests for CRM tool streaming packet emissions and session replay helpers."""

from queue import Queue
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from onyx.chat.emitter import Emitter
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
from onyx.db.enums import CrmContactStatus
from onyx.db.enums import CrmInteractionType
from onyx.db.models import CrmContact
from onyx.db.models import CrmInteraction
from onyx.tools.built_in_tools import CITEABLE_TOOLS_NAMES
from onyx.tools.tool_implementations.crm.crm_create_tool import CrmCreateTool
from onyx.tools.tool_implementations.crm.crm_log_interaction_tool import (
    CrmLogInteractionTool,
)
from onyx.tools.tool_implementations.crm.crm_search_tool import CrmSearchTool
from onyx.tools.tool_implementations.crm.crm_update_tool import CrmUpdateTool


@pytest.fixture
def emitter() -> Emitter:
    bus: Queue = Queue()
    return Emitter(bus)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


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
        assert packet.placement == placement

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
        assert packet.placement == placement

    def test_crm_update_emit_start(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)
        tool.emit_start(placement)

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, CrmUpdateToolStart)
        assert packet.placement == placement

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
        assert packet.placement == placement


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

    def test_crm_update_run_emits_delta(
        self, emitter: Emitter, db_session, placement: Placement
    ) -> None:
        tool = CrmUpdateTool(tool_id=3, db_session=db_session, emitter=emitter)
        contact_id = uuid4()
        contact = CrmContact(
            first_name="Alice",
            status=CrmContactStatus.LEAD,
        )
        contact.id = contact_id
        updated_contact = CrmContact(
            first_name="Alicia",
            status=CrmContactStatus.ACTIVE,
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
                "onyx.tools.tool_implementations.crm.crm_update_tool.get_contact_tags"
            ) as mock_get_tags,
        ):
            mock_get_contact.return_value = contact
            mock_update_contact.return_value = updated_contact
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
