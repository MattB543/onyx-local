"""Regression test: every custom fork tool stays registered in the built-in
tools registry.

The fork adds six CRM tools plus a Google Calendar search tool on top of
upstream. A future upstream sync could silently drop one of these from
``built_in_tools.py`` (e.g. by reverting a manually-blended import block).
This test fails loudly if any custom tool disappears from either the
``BUILT_IN_TOOL_MAP`` (in-code-id -> class) or the ``TOOL_NAME_TO_CLASS``
(LLM-facing-name -> class) registries.

It also documents the full expected set, including upstream's CodingAgentTool,
so the registry's contents are pinned end-to-end.
"""

from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP
from onyx.tools.built_in_tools import get_built_in_tool_by_id
from onyx.tools.built_in_tools import get_built_in_tool_ids
from onyx.tools.built_in_tools import TOOL_NAME_TO_CLASS
from onyx.tools.tool_implementations.calendar.search_calendar_tool import (
    SearchCalendarTool,
)
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)
from onyx.tools.tool_implementations.crm.crm_create_tool import CrmCreateTool
from onyx.tools.tool_implementations.crm.crm_get_tool import CrmGetTool
from onyx.tools.tool_implementations.crm.crm_list_tool import CrmListTool
from onyx.tools.tool_implementations.crm.crm_log_interaction_tool import (
    CrmLogInteractionTool,
)
from onyx.tools.tool_implementations.crm.crm_search_tool import CrmSearchTool
from onyx.tools.tool_implementations.crm.crm_update_tool import CrmUpdateTool

# The six CRM tools that make up the fork's CRM feature.
CRM_TOOLS = [
    CrmSearchTool,
    CrmCreateTool,
    CrmUpdateTool,
    CrmLogInteractionTool,
    CrmListTool,
    CrmGetTool,
]

# All custom fork tools that the sync must preserve in the registry.
CUSTOM_FORK_TOOLS = CRM_TOOLS + [SearchCalendarTool]


def test_all_six_crm_tools_registered_by_in_code_id() -> None:
    """All six CRM tools appear in BUILT_IN_TOOL_MAP keyed by class name."""
    assert len(CRM_TOOLS) == 6
    for tool_cls in CRM_TOOLS:
        in_code_id = tool_cls.__name__
        assert in_code_id in BUILT_IN_TOOL_MAP, (
            f"{in_code_id} missing from BUILT_IN_TOOL_MAP"
        )
        assert BUILT_IN_TOOL_MAP[in_code_id] is tool_cls
        # Public accessor agrees with the map.
        assert get_built_in_tool_by_id(in_code_id) is tool_cls
        assert in_code_id in get_built_in_tool_ids()


def test_search_calendar_tool_registered_by_in_code_id() -> None:
    """The Google Calendar search tool is registered by class name."""
    in_code_id = SearchCalendarTool.__name__
    assert in_code_id in BUILT_IN_TOOL_MAP
    assert BUILT_IN_TOOL_MAP[in_code_id] is SearchCalendarTool
    assert get_built_in_tool_by_id(in_code_id) is SearchCalendarTool


def test_custom_fork_tools_present_in_name_to_class_map() -> None:
    """Every custom tool is reachable via its LLM-facing name as well.

    TOOL_NAME_TO_CLASS maps the name the LLM uses (e.g. ``crm_search``) to
    the tool class. If a custom tool were dropped from BUILT_IN_TOOL_MAP it
    would also vanish here, so this is an independent check on the same guard.
    """
    registered_classes = set(TOOL_NAME_TO_CLASS.values())
    for tool_cls in CUSTOM_FORK_TOOLS:
        assert tool_cls in registered_classes, (
            f"{tool_cls.__name__} missing from TOOL_NAME_TO_CLASS"
        )

    # Spot-check that the LLM-facing names resolve back to the right classes.
    assert TOOL_NAME_TO_CLASS[CrmSearchTool.NAME] is CrmSearchTool
    assert TOOL_NAME_TO_CLASS[CrmCreateTool.NAME] is CrmCreateTool
    assert TOOL_NAME_TO_CLASS[CrmUpdateTool.NAME] is CrmUpdateTool
    assert TOOL_NAME_TO_CLASS[CrmLogInteractionTool.NAME] is CrmLogInteractionTool
    assert TOOL_NAME_TO_CLASS[CrmListTool.NAME] is CrmListTool
    assert TOOL_NAME_TO_CLASS[CrmGetTool.NAME] is CrmGetTool
    assert TOOL_NAME_TO_CLASS[SearchCalendarTool.NAME] is SearchCalendarTool


def test_crm_tool_names_are_unique_and_expected() -> None:
    """Guard against two CRM tools colliding on the same LLM-facing name,
    which would silently overwrite one in TOOL_NAME_TO_CLASS."""
    names = [tool_cls.NAME for tool_cls in CUSTOM_FORK_TOOLS]
    assert len(names) == len(set(names)), f"duplicate tool names: {names}"
    assert set(names) == {
        "crm_search",
        "crm_create",
        "crm_update",
        "crm_log_interaction",
        "crm_list",
        "crm_get",
        "search_calendar",
    }


def test_upstream_coding_agent_tool_also_present() -> None:
    """Document that upstream's CodingAgentTool was kept during the sync's
    manual blend (CRM/calendar tools added *alongside* it, not replacing it)."""
    assert CodingAgentTool.__name__ in BUILT_IN_TOOL_MAP
    assert BUILT_IN_TOOL_MAP[CodingAgentTool.__name__] is CodingAgentTool
    assert CodingAgentTool in set(TOOL_NAME_TO_CLASS.values())
