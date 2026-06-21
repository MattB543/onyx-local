"""Tests for the crm_list AI tool: date-range filters and sort direction."""

from datetime import datetime
from datetime import timezone
from queue import Queue
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.crm.crm_list_tool import CrmListTool


class _TestBus:
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


@pytest.fixture
def placement() -> Placement:
    return Placement(turn_index=0, tab_index=0)


@pytest.fixture(autouse=True)
def patch_stage_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.crm.crm_list_tool.get_allowed_contact_stages",
        lambda _db_session: ["lead", "active", "inactive", "archived"],
    )


def _make_tool(db_session, emitter: Emitter) -> CrmListTool:
    return CrmListTool(tool_id=1, db_session=db_session, emitter=emitter)


def test_crm_list_tool_definition_exposes_date_and_sort_params(
    db_session, emitter: Emitter
) -> None:
    tool = _make_tool(db_session, emitter)
    props = tool.tool_definition()["function"]["parameters"]["properties"]
    for key in (
        "sort_by",
        "sort_dir",
        "created_after",
        "created_before",
        "updated_after",
        "updated_before",
    ):
        assert key in props
    assert tool.tool_definition()["function"]["parameters"]["required"] == [
        "entity_type"
    ]


def test_crm_list_contacts_passes_parsed_filters(
    db_session, emitter: Emitter, placement: Placement
) -> None:
    tool = _make_tool(db_session, emitter)

    with patch(
        "onyx.tools.tool_implementations.crm.crm_list_tool.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        tool.run(
            placement=placement,
            entity_type="contact",
            created_after="2026-01-01",
            sort_dir="asc",
        )

    kwargs = mock_list_contacts.call_args.kwargs
    assert isinstance(kwargs["created_after"], datetime)
    assert kwargs["created_after"].tzinfo is not None
    assert kwargs["created_after"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert kwargs["sort_dir"] == "asc"


def test_crm_list_organizations_passes_parsed_filters(
    db_session, emitter: Emitter, placement: Placement
) -> None:
    tool = _make_tool(db_session, emitter)

    with patch(
        "onyx.tools.tool_implementations.crm.crm_list_tool.list_organizations",
        return_value=([], 0),
    ) as mock_list_organizations:
        tool.run(
            placement=placement,
            entity_type="organization",
            updated_before="2026-03-01T08:00:00Z",
            sort_by="created_at",
            sort_dir="desc",
        )

    kwargs = mock_list_organizations.call_args.kwargs
    assert kwargs["updated_before"] == datetime(
        2026, 3, 1, 8, 0, tzinfo=timezone.utc
    )
    assert kwargs["sort_by"] == "created_at"
    assert kwargs["sort_dir"] == "desc"


def test_crm_list_bare_date_before_extends_to_end_of_day(
    db_session, emitter: Emitter, placement: Placement
) -> None:
    tool = _make_tool(db_session, emitter)

    with patch(
        "onyx.tools.tool_implementations.crm.crm_list_tool.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        tool.run(
            placement=placement,
            entity_type="contact",
            created_before="2026-01-31",
        )

    kwargs = mock_list_contacts.call_args.kwargs
    # bare-date upper bound covers the whole day; lower bound stays at midnight
    assert kwargs["created_before"] == datetime(
        2026, 1, 31, 23, 59, 59, 999999, tzinfo=timezone.utc
    )


def test_crm_list_explicit_midnight_before_not_extended(
    db_session, emitter: Emitter, placement: Placement
) -> None:
    tool = _make_tool(db_session, emitter)

    with patch(
        "onyx.tools.tool_implementations.crm.crm_list_tool.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        tool.run(
            placement=placement,
            entity_type="contact",
            created_before="2026-01-31T00:00:00Z",
        )

    kwargs = mock_list_contacts.call_args.kwargs
    assert kwargs["created_before"] == datetime(
        2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc
    )


def test_crm_list_contacts_rejects_bad_datetime(
    db_session, emitter: Emitter, placement: Placement
) -> None:
    tool = _make_tool(db_session, emitter)

    with patch(
        "onyx.tools.tool_implementations.crm.crm_list_tool.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        with pytest.raises(ToolCallException):
            tool.run(
                placement=placement,
                entity_type="contact",
                created_after="nonsense",
            )

    mock_list_contacts.assert_not_called()


def test_crm_list_contacts_rejects_bad_sort_dir(
    db_session, emitter: Emitter, placement: Placement
) -> None:
    tool = _make_tool(db_session, emitter)

    with patch(
        "onyx.tools.tool_implementations.crm.crm_list_tool.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        with pytest.raises(ToolCallException):
            tool.run(
                placement=placement,
                entity_type="contact",
                sort_dir="up",
            )

    mock_list_contacts.assert_not_called()


def test_crm_list_naive_datetime_coerced_to_utc(
    db_session, emitter: Emitter, placement: Placement
) -> None:
    tool = _make_tool(db_session, emitter)

    with patch(
        "onyx.tools.tool_implementations.crm.crm_list_tool.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        tool.run(
            placement=placement,
            entity_type="contact",
            created_after="2026-01-01T00:00:00",
        )

    created_after = mock_list_contacts.call_args.kwargs["created_after"]
    assert created_after.tzinfo is not None
    assert created_after.utcoffset().total_seconds() == 0
