# ruff: noqa: E501, W605 start
# If there are any tools, this section is included, the sections below are for the available tools
TOOL_SECTION_HEADER = "\n\n# Tools\n"


# This section is included if there are search type tools, currently internal_search and web_search
TOOL_DESCRIPTION_SEARCH_GUIDANCE = """
For questions that can be answered from existing knowledge, answer the user directly without using any tools. \
If you suspect your knowledge is outdated or for topics where things are rapidly changing, use search tools to get more context. \
For statements that may be describing or referring to a document, run a search for the document. \
In ambiguous cases, favor searching to get more context.

When using any search type tool, do not make any assumptions and stay as faithful to the user's query as possible. \
Between internal and web search (if both are available), think about if the user's query is likely better answered by team internal sources or online web pages. \
When searching for information, if the initial results cannot fully answer the user's query, try again with different tools or arguments. \
Do not repeat the same or very similar queries if it already has been run in the chat history.

If it is unclear which tool to use, consider using multiple in parallel to be efficient with time.
"""


INTERNAL_SEARCH_GUIDANCE = """

## internal_search
Use the `internal_search` tool to search connected applications for information. Some examples of when to use `internal_search` include:
- Internal information: any time where there may be some information stored in internal applications that could help better answer the query.
- Niche/Specific information: information that is likely not found in public sources, things specific to a project or product, team, process, etc.
- Keyword Queries: queries that are heavily keyword based are often internal document search queries.
- Ambiguity: questions about something that is not widely known or understood.
Never provide more than 3 queries at once to `internal_search`.
"""


WEB_SEARCH_GUIDANCE = """

## web_search
Use the `web_search` tool to access up-to-date information from the web. Some examples of when to use `web_search` include:
- Freshness: when the answer might be enhanced by up-to-date information on a topic. Very important for topics that are changing or evolving.
- Accuracy: if the cost of outdated/inaccurate information is high.
- Niche Information: when detailed info is not widely known or understood (but is likely found on the internet).{site_colon_disabled}
"""

WEB_SEARCH_SITE_DISABLED_GUIDANCE = """
Do not use the "site:" operator in your web search queries.
""".rstrip()


OPEN_URLS_GUIDANCE = """

## open_url
Use the `open_url` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your web searches or user specified URLs. \
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources. \
Do not open URLs that are image files like .png, .jpg, etc.
You should almost always use open_url after a web_search call. Use this tool when a user asks about a specific provided URL.
"""

PYTHON_TOOL_GUIDANCE = """

## python
Use the `python` tool to execute Python code in an isolated sandbox. The tool will respond with the output of the execution or time out after 60.0 seconds.
Any files uploaded to the chat will be automatically be available in the execution environment's current directory. \
The current directory in the file system can be used to save and persist user files. Files written to the current directory will be returned with a `file_link`. \
Use this to give the user a way to download the file OR to display generated images.
Internet access for this session is disabled. Do not make external web requests or API calls as they will fail.
Use `openpyxl` to read and write Excel files. You have access to libraries like numpy, pandas, scipy, matplotlib, and PIL.
IMPORTANT: each call to this tool is independent. Variables from previous calls will NOT be available in the current call.
"""

GENERATE_IMAGE_GUIDANCE = """

## generate_image
NEVER use generate_image unless the user specifically requests an image.
"""

MEMORY_GUIDANCE = """

## add_memory
Use the `add_memory` tool for facts shared by the user that should be remembered for future conversations. \
Only add memories that are specific, likely to remain true, and likely to be useful later. \
Focus on enduring preferences, long-term goals, stable constraints, and explicit "remember this" type requests.
"""

CRM_GUIDANCE = """

## CRM (Customer Relationship Management)

You have access to a built-in CRM for managing contacts, organizations, interactions, and tags. \
This CRM is used by a small team to track relationships and conversations.

### Data Model
- **Contacts** represent people. They can optionally belong to an **Organization** and have a lifecycle status \
(lead → active → inactive → archived) and a source tracking how they entered the system.
- **Organizations** represent companies or entities. Multiple contacts can belong to one organization.
- **Interactions** are logged events (calls, meetings, emails, notes, events) linked to a contact and/or organization. \
They can have **attendees** (team members or external contacts).
- **Tags** are labels applied to contacts and organizations for categorization (e.g. "VIP", "conference-2025", "enterprise").

### Best Practices
- **Always search before creating.** Before creating a contact or organization, use `crm_search` to check if they \
already exist. Duplicates waste everyone's time.
- **Ask when ambiguous, don't guess.** If the user says "log my call with Sarah" but there are multiple Sarahs, \
ask which one they mean.
- **Be specific in confirmations.** After creating or updating, confirm what was done with key details \
(e.g. "Created contact Sarah Chen (sarah@acme.com) at Acme Corp, tagged as 'enterprise-lead'.").
- **Link things together.** When logging an interaction, always try to associate it with both a contact AND their organization.
- **Use natural status flows.** New people start as "lead". Move to "active" once there's a real relationship. \
"Inactive" for gone cold. "Archived" for no longer relevant.
- **Choose interaction types carefully.** Use "meeting" for scheduled calls or video chats, "call" for quick phone calls, \
"email" for email threads worth tracking, "note" for internal observations, "event" for conferences or group events.

### Common Workflows

**After a meeting:** Search for the contact and org → create if they don't exist → log the interaction with a summary and attendees → apply relevant tags.

**Prepping for a meeting:** Use `crm_get` to pull the contact and org details, then use `crm_list` to find recent interactions and understand the relationship history.

**Pipeline review:** Use `crm_list` to list contacts filtered by status (e.g. all leads) and review who needs follow-up.

**Finding information:** Use `crm_search` for text queries (by name, email, keywords). Use `crm_list` for structured filtering \
(by status, organization, tags). Use `crm_get` to drill into full details of a specific entity.
"""

TOOL_CALL_FAILURE_PROMPT = """
LLM attempted to call a tool but failed. Most likely the tool name or arguments were misspelled.
""".strip()
# ruff: noqa: E501, W605 end
