"""A failed CRM or Calendar Search call streams its error as the tool's result
delta, and session replay turns the stored error into the same payload. An
unexpected exception streams and stores a generic message only."""

from collections.abc import Callable, Generator
from queue import Empty, Queue
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.session_loading import (
    _parse_crm_tool_payload,
    create_calendar_search_packets,
    create_crm_search_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    CalendarSearchToolDelta,
    CrmCreateToolDelta,
    CrmGetToolDelta,
    CrmListToolDelta,
    CrmLogInteractionToolDelta,
    CrmSearchToolDelta,
    CrmUpdateToolDelta,
    Packet,
    SectionEnd,
)
from onyx.tools.interface import Tool
from onyx.tools.models import (
    ToolCallException,
    ToolCallKickoff,
    ToolExecutionException,
)
from onyx.tools.tool_implementations.calendar.search_calendar_tool import (
    SearchCalendarTool,
)
from onyx.tools.tool_implementations.crm.crm_create_tool import CrmCreateTool
from onyx.tools.tool_implementations.crm.crm_get_tool import CrmGetTool
from onyx.tools.tool_implementations.crm.crm_list_tool import CrmListTool
from onyx.tools.tool_implementations.crm.crm_log_interaction_tool import (
    CrmLogInteractionTool,
)
from onyx.tools.tool_implementations.crm.crm_search_tool import CrmSearchTool
from onyx.tools.tool_implementations.crm.crm_update_tool import CrmUpdateTool
from onyx.tools.tool_implementations.error_delta import (
    UNEXPECTED_TOOL_ERROR_MESSAGE,
    PayloadToolDelta,
    stream_tool_call_error,
)
from onyx.tools.tool_runner import _safe_run_single_tool

PLACEMENT = Placement(turn_index=2, tab_index=1)

ToolFactory = Callable[[Session, Emitter], Tool[None]]

TOOLS: list[tuple[ToolFactory, type[PayloadToolDelta]]] = [
    (lambda db, em: CrmSearchTool(1, db, em), CrmSearchToolDelta),
    (lambda db, em: CrmCreateTool(2, db, em, str(uuid4())), CrmCreateToolDelta),
    (lambda db, em: CrmUpdateTool(3, db, em), CrmUpdateToolDelta),
    (
        lambda db, em: CrmLogInteractionTool(4, db, em, str(uuid4())),
        CrmLogInteractionToolDelta,
    ),
    (lambda db, em: CrmListTool(5, db, em), CrmListToolDelta),
    (lambda db, em: CrmGetTool(6, db, em), CrmGetToolDelta),
    (lambda db, em: SearchCalendarTool(7, db, em), CalendarSearchToolDelta),
]
TOOL_IDS = [delta.__name__ for _, delta in TOOLS]


def _drain(bus: Queue) -> list[Packet]:
    packets: list[Packet] = []
    while True:
        try:
            _, packet = bus.get_nowait()
        except Empty:
            return packets
        packets.append(packet)


def _same_slot(a: Placement, b: Placement) -> bool:
    """The emitter stamps model_index, so compare the timeline slot only."""
    return (a.turn_index, a.tab_index) == (b.turn_index, b.tab_index)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = sessionmaker(bind=create_engine("sqlite://"))()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _stage_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """The create, update and list tools read CRM settings on init."""
    for module in ("crm_create_tool", "crm_update_tool", "crm_list_tool"):
        path = f"onyx.tools.tool_implementations.crm.{module}"
        monkeypatch.setattr(
            f"{path}.get_allowed_contact_stages", lambda _db: ["lead", "active"]
        )
        monkeypatch.setattr(f"{path}.get_contact_category_options", lambda _db: [])


def test_wrapper_emits_one_error_delta_and_reraises() -> None:
    bus: Queue = Queue()
    error = ToolCallException(message="trace detail", llm_facing_message="Bad id.")

    with pytest.raises(ToolCallException) as exc_info:
        with stream_tool_call_error(Emitter(bus), PLACEMENT, CrmGetToolDelta):
            raise error

    assert exc_info.value is error
    (packet,) = _drain(bus)
    assert _same_slot(packet.placement, PLACEMENT)
    assert isinstance(packet.obj, CrmGetToolDelta)
    assert packet.obj.payload == {"error": "Bad id."}


def test_wrapper_emits_nothing_on_success() -> None:
    bus: Queue = Queue()

    with stream_tool_call_error(Emitter(bus), PLACEMENT, CrmGetToolDelta):
        pass

    assert _drain(bus) == []


def test_wrapper_hides_an_unexpected_error_behind_a_generic_one() -> None:
    bus: Queue = Queue()
    original = RuntimeError("password=hunter2 in a driver error")

    with pytest.raises(ToolCallException) as exc_info:
        with stream_tool_call_error(Emitter(bus), PLACEMENT, CrmGetToolDelta):
            raise original

    assert exc_info.value.__cause__ is original
    assert exc_info.value.llm_facing_message == UNEXPECTED_TOOL_ERROR_MESSAGE
    (packet,) = _drain(bus)
    assert isinstance(packet.obj, CrmGetToolDelta)
    assert packet.obj.payload == {"error": UNEXPECTED_TOOL_ERROR_MESSAGE}


class _Interrupt(BaseException):
    pass


@pytest.mark.parametrize(
    "error",
    [
        # The runner handles it itself and can emit a PacketException.
        ToolExecutionException("sandbox failed", emit_error_packet=True),
        _Interrupt(),
    ],
    ids=["ToolExecutionException", "BaseException"],
)
def test_wrapper_lets_runner_handled_errors_through(error: BaseException) -> None:
    bus: Queue = Queue()

    with pytest.raises(type(error)) as exc_info:
        with stream_tool_call_error(Emitter(bus), PLACEMENT, CrmGetToolDelta):
            raise error

    assert exc_info.value is error
    assert _drain(bus) == []


@pytest.mark.parametrize(("make_tool", "delta_type"), TOOLS, ids=TOOL_IDS)
def test_argument_error_streams_as_the_tool_delta(
    db_session: Session,
    make_tool: ToolFactory,
    delta_type: type[PayloadToolDelta],
) -> None:
    """Argument checks run before the main body; their errors stream too."""
    bus: Queue = Queue()
    tool = make_tool(db_session, Emitter(bus))

    with pytest.raises(ToolCallException) as exc_info:
        tool.run(placement=PLACEMENT, override_kwargs=None, bogus_argument=1)

    (packet,) = _drain(bus)
    assert _same_slot(packet.placement, PLACEMENT)
    assert isinstance(packet.obj, delta_type)
    assert packet.obj.payload == {"error": exc_info.value.llm_facing_message}


@pytest.mark.parametrize(
    "unexpected", [False, True], ids=["tool_call_error", "unexpected_error"]
)
def test_live_error_matches_replay(db_session: Session, unexpected: bool) -> None:
    """The runner stores the error text; replay rebuilds the live delta."""
    bus: Queue = Queue()
    tool = CrmGetTool(1, db_session, Emitter(bus))
    tool_call = ToolCallKickoff(
        tool_call_id="call-1",
        tool_name=tool.name,
        tool_args={
            "entity_type": "contact",
            "entity_id": str(uuid4()) if unexpected else "not-a-uuid",
        },
        placement=PLACEMENT,
    )

    with patch.object(
        CrmGetTool, "_get_contact", side_effect=RuntimeError("raw driver detail")
    ):
        response = _safe_run_single_tool(tool, tool_call, None)

    delta, section_end = _drain(bus)
    assert isinstance(delta.obj, CrmGetToolDelta)
    assert isinstance(section_end.obj, SectionEnd)
    assert _parse_crm_tool_payload(response.llm_facing_response) == delta.obj.payload
    assert "raw driver detail" not in response.llm_facing_response
    if unexpected:
        assert delta.obj.payload == {"error": UNEXPECTED_TOOL_ERROR_MESSAGE}


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (
            "Tool failed with error: 'query' is required.",
            {"error": "'query' is required."},
        ),
        ('{"status": "ok"}', {"status": "ok"}),
        ("[1, 2]", {"result": [1, 2]}),
        ("not json", {"result": "not json"}),
        (None, {}),
    ],
)
def test_parse_crm_tool_payload(stored: str | None, expected: dict[str, Any]) -> None:
    assert _parse_crm_tool_payload(stored) == expected


def test_replay_packets_carry_the_error() -> None:
    stored = "Tool failed with error: Could not find a contact with that ID."
    for packets in (
        create_crm_search_packets(stored, turn_index=0),
        create_calendar_search_packets(stored, turn_index=0),
    ):
        _start, delta, _end = packets
        assert isinstance(delta.obj, CrmSearchToolDelta | CalendarSearchToolDelta)
        assert delta.obj.payload == {"error": "Could not find a contact with that ID."}
