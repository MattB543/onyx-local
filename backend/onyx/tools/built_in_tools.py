from typing import Type
from typing import Union

from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.knowledge_graph.knowledge_graph_tool import (
    KnowledgeGraphTool,
)
from onyx.tools.tool_implementations.crm.crm_create_tool import CrmCreateTool
from onyx.tools.tool_implementations.crm.crm_log_interaction_tool import (
    CrmLogInteractionTool,
)
from onyx.tools.tool_implementations.crm.crm_search_tool import CrmSearchTool
from onyx.tools.tool_implementations.crm.crm_update_tool import CrmUpdateTool
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


BUILT_IN_TOOL_TYPES = Union[
    SearchTool,
    ImageGenerationTool,
    WebSearchTool,
    KnowledgeGraphTool,
    OpenURLTool,
    PythonTool,
    FileReaderTool,
    MemoryTool,
    CrmSearchTool,
    CrmCreateTool,
    CrmUpdateTool,
    CrmLogInteractionTool,
]

BUILT_IN_TOOL_MAP: dict[str, Type[BUILT_IN_TOOL_TYPES]] = {
    SearchTool.__name__: SearchTool,
    ImageGenerationTool.__name__: ImageGenerationTool,
    WebSearchTool.__name__: WebSearchTool,
    KnowledgeGraphTool.__name__: KnowledgeGraphTool,
    OpenURLTool.__name__: OpenURLTool,
    PythonTool.__name__: PythonTool,
    FileReaderTool.__name__: FileReaderTool,
    MemoryTool.__name__: MemoryTool,
    CrmSearchTool.__name__: CrmSearchTool,
    CrmCreateTool.__name__: CrmCreateTool,
    CrmUpdateTool.__name__: CrmUpdateTool,
    CrmLogInteractionTool.__name__: CrmLogInteractionTool,
}

STOPPING_TOOLS_NAMES: list[str] = [ImageGenerationTool.NAME]
CITEABLE_TOOLS_NAMES: list[str] = [
    SearchTool.NAME,
    WebSearchTool.NAME,
    OpenURLTool.NAME,
    CrmSearchTool.NAME,
]


def get_built_in_tool_ids() -> list[str]:
    return list(BUILT_IN_TOOL_MAP.keys())


def get_built_in_tool_by_id(in_code_tool_id: str) -> Type[BUILT_IN_TOOL_TYPES]:
    return BUILT_IN_TOOL_MAP[in_code_tool_id]
