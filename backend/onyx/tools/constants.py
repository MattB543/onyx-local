"""Tool name and ID constants matching frontend definitions."""

# Tool names as referenced by tool results / tool calls
SEARCH_TOOL_NAME = "run_search"
INTERNET_SEARCH_TOOL_NAME = "run_internet_search"
IMAGE_GENERATION_TOOL_NAME = "run_image_generation"
PYTHON_TOOL_NAME = "run_python"
OPEN_URL_TOOL_NAME = "open_url"
CRM_SEARCH_TOOL_NAME = "crm_search"
CRM_CREATE_TOOL_NAME = "crm_create"
CRM_UPDATE_TOOL_NAME = "crm_update"
CRM_LOG_INTERACTION_TOOL_NAME = "crm_log_interaction"

# In-code tool IDs that also correspond to the tool's name when associated with a persona
SEARCH_TOOL_ID = "SearchTool"
IMAGE_GENERATION_TOOL_ID = "ImageGenerationTool"
WEB_SEARCH_TOOL_ID = "WebSearchTool"
PYTHON_TOOL_ID = "PythonTool"
OPEN_URL_TOOL_ID = "OpenURLTool"
FILE_READER_TOOL_ID = "FileReaderTool"
CRM_SEARCH_TOOL_ID = "CrmSearchTool"
CRM_CREATE_TOOL_ID = "CrmCreateTool"
CRM_UPDATE_TOOL_ID = "CrmUpdateTool"
CRM_LOG_INTERACTION_TOOL_ID = "CrmLogInteractionTool"

# Tool names as referenced by tool results / tool calls (read_file)
FILE_READER_TOOL_NAME = "read_file"
