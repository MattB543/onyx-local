# Feature Development Playbook

Last updated: February 16, 2026

This guide captures the implementation pattern we used for the CRM feature so future features (new DB tables, APIs, UI pages, and AI tools) can follow a predictable, low-risk path.

Use this as the default blueprint for any new product surface that spans:
- Database schema + data access layer
- Backend API
- Tool-calling / AI integration
- Streaming packet rendering
- Frontend pages and data hooks
- Tests and rollout

## 1. Core Principles

- Build in thin vertical slices behind a feature flag when possible.
- Keep one source of truth per layer:
  - ORM schema in `backend/onyx/db/models.py`
  - DB operations in a dedicated module under `backend/onyx/db/`
  - API contracts in `backend/onyx/server/features/<feature>/models.py`
  - Typed FE API client in `web/src/app/app/<feature>/<feature>Service.ts`
- Reuse established repo patterns over custom architecture.
- Prefer deterministic behavior over smart-but-ambiguous behavior (especially for AI tools).

## 2. Golden Path (Recommended Sequence)

1. Design entities, enums, and API contracts.
2. Add ORM models + Alembic migration(s).
3. Add DB query layer functions (`create`, `get`, `list`, `update`, `search`, etc.).
4. Add backend feature module (`api.py`, `models.py`) and wire router in `backend/onyx/main.py`.
5. Add AI tools (if needed) and wire tool system integration points.
6. Add streaming packet types (backend + frontend) and renderer integration.
7. Add frontend typed service, SWR hooks, and pages.
8. Add feature gating in navigation/UI entry points.
9. Add tests at every layer.
10. Validate locally, then roll out with migrations and flag control.

## 3. Database Layer Blueprint

### 3.1 Add enums (if needed)

File: `backend/onyx/db/enums.py`

Guidelines:
- Use explicit string enums.
- In SQLAlchemy models, use `Enum(MyEnum, native_enum=False)` for consistency with existing repo behavior.

### 3.2 Add ORM models

File: `backend/onyx/db/models.py`

Checklist:
- Add tables/classes with explicit types.
- Add `created_at` and `updated_at` for mutable entities.
- Use `onupdate=func.now()` on mutable `updated_at` columns.
- Use FK `ondelete` behaviors intentionally (`CASCADE`, `SET NULL`, etc.).
- Add generated/search columns where relevant (for example, `search_tsv`).

CRM reference entities:
- `CrmContact`
- `CrmOrganization`
- `CrmInteraction`
- `CrmTag`
- join tables and settings tables

### 3.3 Add migrations

Folder: `backend/alembic/versions/`

Pattern used in CRM:
- Migration A: create schema, constraints, indexes, generated search columns.
- Migration B: seed tool rows / persona mappings.
- Migration C (follow-up): patch schema corrections discovered in review.

Commands (from `backend/`):
```bash
alembic revision -m "add_<feature>_core_schema"
alembic upgrade head
```

Notes:
- Do not rely on `--autogenerate` in this repo.
- Populate `upgrade()` and `downgrade()` manually.
- See `backend/alembic/README.md` for tenant-wide migration options.

### 3.4 Create DB query layer

Create: `backend/onyx/db/<feature>.py`

Put business-level DB functions here, not in API routes.

Recommended function groups:
- Settings: `get_or_create_*`, `update_*_settings`
- Core CRUD: `create_*`, `get_*_by_id`, `list_*`, `update_*`
- Relationships: association add/remove helpers
- Search: cross-entity search function
- Resolution helpers: any matching/disambiguation logic for tool flows

Important lessons from CRM:
- Normalize and validate user input in DB functions.
- Use mutable field allowlists in update functions.
- Escape wildcard metacharacters for user-driven `ILIKE` queries.
  - Use helper style equivalent to `_escape_like_query`.
  - Use `ilike(pattern, escape="\\")`.
- Keep dedup logic in Python before insert when upsert semantics are tricky.

## 4. Backend API Blueprint

### 4.1 Create feature module

Create:
- `backend/onyx/server/features/<feature>/api.py`
- `backend/onyx/server/features/<feature>/models.py`
- `backend/onyx/server/features/<feature>/__init__.py`

Then wire router in:
- `backend/onyx/main.py`

### 4.2 API contract conventions

Follow existing API conventions:
- Prefix: `/user/<feature>`
- Pagination query params: `page_num`, `page_size`
- Pagination response: `PaginatedReturn[T]` (`items`, `total_items`)
- Use typed request/response models for each endpoint

### 4.3 Auth requirement (critical)

Every non-public endpoint must include a recognized auth dependency, usually:
- `Depends(current_user)`

Reason:
- Startup auth validation in `backend/onyx/server/auth_check.py` fails app startup if private routes do not include recognized auth dependencies.

### 4.4 API error handling conventions

- `404`: missing resource
- `409`: uniqueness/conflict
- `400`: validation issues
- Translate DB exceptions to stable API error messages.

## 5. AI Tooling Blueprint

### 5.1 Prefer granular tool design

For complex domains, prefer multiple focused tools (search/create/update/log) over one mega-tool.

Why:
- Better tool routing by the LLM
- Cleaner JSON schemas
- Easier disambiguation and auditing
- Simpler test coverage per operation

### 5.2 Tool files and shared utilities

Recommended structure:
- `backend/onyx/tools/tool_implementations/<feature>/models.py`
- `backend/onyx/tools/tool_implementations/<feature>/<feature>_search_tool.py`
- additional operation tools as needed

Add shared helpers for:
- Input parsing (`UUID`, enums, datetime)
- Payload serialization
- Payload compaction
- Schema availability checks

### 5.3 Integrate tool registry + construction

Update all required integration points:
- `backend/onyx/tools/constants.py`
- `backend/onyx/tools/built_in_tools.py`
- `backend/onyx/tools/tool_constructor.py`

`tool_constructor.py` is explicit branch-based construction, so each new built-in tool needs its own `elif` branch.

### 5.4 Availability and safety

Every new tool class should implement `is_available()` to verify required preconditions (for example, required tables exist) before the tool is exposed.

### 5.5 Citation decision is explicit

Decide whether tool output should influence citations.
- If yes, add tool name to `CITEABLE_TOOLS_NAMES` in `backend/onyx/tools/built_in_tools.py`.
- If no, document rationale in PR notes.

## 6. Streaming and Timeline Integration Blueprint

If tools stream custom packets, wire both backend and frontend.

### 6.1 Backend streaming

Update:
- `backend/onyx/server/query_and_chat/streaming_models.py`

Add:
- New `StreamingType` enum entries
- Start/delta packet models
- `PacketObj` union entries

### 6.2 Session replay support

Update:
- `backend/onyx/server/query_and_chat/session_loading.py`

Add replay packet builders so historical sessions render correctly after refresh.

### 6.3 Frontend streaming types and packet handling

Update:
- `web/src/app/app/services/streamingModels.ts`
- `web/src/app/app/services/packetUtils.ts`
- `web/src/app/app/message/messageComponents/toolDisplayHelpers.tsx`
- Timeline renderer routing (`renderMessageComponent.tsx` and renderer files)

Add or update:
- Dedicated renderer under `web/src/app/app/message/messageComponents/timeline/renderers/<feature>/`

## 7. Frontend Page Blueprint

### 7.1 Keep app-router pages thin

Under `web/src/app/app/<feature>/.../page.tsx`, keep wrappers minimal.

Example pattern:
- `web/src/app/app/crm/contacts/page.tsx` only returns `CrmContactsPage` from `refresh-pages`.

### 7.2 Put full page implementations in refresh-pages

Implement full pages in:
- `web/src/refresh-pages/`
- Shared feature nav/components in a subfolder (for example `web/src/refresh-pages/crm/CrmNav.tsx`).

### 7.3 Typed FE service layer

Add a dedicated typed service module:
- `web/src/app/app/<feature>/<feature>Service.ts`

Include:
- All interfaces/types
- Query param builder helper
- Reusable GET/POST/PATCH/DELETE wrappers

### 7.4 Extract SWR hooks

Place simple fetch hooks in:
- `web/src/lib/hooks/`

Examples:
- `useCrmContacts`
- `useCrmContact`
- `useCrmInteractions`

Keep mutation-heavy or app-wide hooks in `web/src/hooks/` when appropriate.

### 7.5 Forms and UI components

Follow design system and form stack:
- Formik + Yup
- `refresh-components` inputs/buttons/text components

Avoid raw HTML controls unless no design-system component exists.

### 7.6 Feature gate entry points

For navigation and routes, gate availability based on settings/flags.

CRM example:
- Sidebar button uses CRM settings gate in `web/src/sections/sidebar/AppSidebar.tsx`.
- App focus recognizes route family in `web/src/hooks/useAppFocus.ts`.

## 8. Testing Blueprint

### 8.1 Backend tests

Add unit tests for:
- DB query layer: `backend/tests/unit/onyx/db/test_<feature>_queries.py`
- Tool packet behavior and run paths: `backend/tests/unit/tools/test_<feature>_tool_packets.py`

Include both:
- Edge-case validation tests
- Happy-path behavior tests

Must cover:
- CRUD with real assertions
- Search with actual returned rows
- Any disambiguation/resolution logic
- Escaping and ordering behavior where relevant

### 8.2 Frontend tests

Add or extend tests for:
- Packet classification (`packetUtils.test.ts`)
- Timeline packet processing (`packetProcessor.test.ts`)
- Feature-specific renderer behavior where practical

Ensure start -> delta -> section-end flows are explicitly tested for new tool packet types.

### 8.3 Suggested validation commands

Backend:
```bash
uv run pytest backend/tests/unit/onyx/db/test_<feature>_queries.py backend/tests/unit/tools/test_<feature>_tool_packets.py -q
```

Frontend:
```bash
pnpm test -- src/app/app/services/packetUtils.test.ts --runInBand
pnpm test -- src/app/app/message/messageComponents/timeline/hooks/packetProcessor.test.ts --runInBand
```

## 9. Rollout and Operations

1. Apply migrations in dev/staging.
2. Validate seeded tool rows and persona mappings.
3. Keep feature flag off by default if behavior is incomplete.
4. Enable for internal users first.
5. Monitor errors and add follow-up migration if schema adjustment is needed.

For multi-tenant setups, use Alembic tenant flags documented in `backend/alembic/README.md`.

## 10. Common Failure Modes (from CRM) and Preventive Checks

- Missing mutable timestamp on editable tables.
  - Preventive check: every mutable entity has `updated_at` in ORM, API snapshot, FE type, and migration.
- Tool added but not fully wired.
  - Preventive check: constants + built_in_tools + constructor + streaming + replay + FE renderer + tests all updated.
- Feature routes fail startup auth check.
  - Preventive check: every route has `Depends(current_user)` (or approved auth dependency).
- `ILIKE` wildcard injection in search filters.
  - Preventive check: escape `%` and `_`, and pass explicit escape char.
- Missing citation behavior decision.
  - Preventive check: decide and set `CITEABLE_TOOLS_NAMES` intentionally.
- Session reload loses tool visuals.
  - Preventive check: add packet replay builders in `session_loading.py`.

## 11. Copy/Paste Implementation Checklist

Use this checklist in PR descriptions for new cross-stack features.

### Design
- [ ] Entity model and API contract reviewed
- [ ] Tooling strategy decided (none vs granular tools)
- [ ] Feature gating strategy defined

### Backend Data
- [ ] Enums added (if needed)
- [ ] ORM models added/updated
- [ ] `created_at` and `updated_at` correctness verified
- [ ] Migration(s) created and manually reviewed
- [ ] DB query module added with normalization + validation
- [ ] Search queries protect against wildcard metacharacter misuse

### Backend API
- [ ] Feature `api.py` and `models.py` added
- [ ] Router included in `backend/onyx/main.py`
- [ ] All endpoints have auth dependencies
- [ ] Pagination uses `page_num`/`page_size` + `PaginatedReturn`

### AI Tools (if applicable)
- [ ] Tool implementation files created
- [ ] `is_available()` implemented
- [ ] Tool constants and built-in registration added
- [ ] Constructor branches added in `tool_constructor.py`
- [ ] Payload compaction + stable serialization implemented
- [ ] Citable behavior decision applied

### Streaming + FE Integration
- [ ] Backend streaming packet types added
- [ ] Session replay packet builders added
- [ ] Frontend packet types and packet utils updated
- [ ] Timeline renderer added and routed
- [ ] Tool display labels/helpers updated

### Frontend Feature UI
- [ ] Thin app router pages added
- [ ] `refresh-pages` components added
- [ ] Typed service module added
- [ ] SWR hooks extracted
- [ ] Forms use Formik + Yup + design system components
- [ ] Sidebar/app focus/entry points gated correctly

### Tests and Validation
- [ ] Backend DB unit tests include happy-path and edge cases
- [ ] Backend tool tests include run-path packet assertions
- [ ] Frontend packet classification tests updated
- [ ] Frontend timeline packet processor tests updated
- [ ] Targeted test commands executed and results captured

## 12. CRM Reference Map (Concrete Example)

When in doubt, use CRM as the reference implementation:
- DB layer: `backend/onyx/db/crm.py`
- API models/routes: `backend/onyx/server/features/crm/models.py`, `backend/onyx/server/features/crm/api.py`
- Tool implementations: `backend/onyx/tools/tool_implementations/crm/`
- Streaming models/replay: `backend/onyx/server/query_and_chat/streaming_models.py`, `backend/onyx/server/query_and_chat/session_loading.py`
- FE service/hooks/pages:
  - `web/src/app/app/crm/crmService.ts`
  - `web/src/lib/hooks/useCrm*.ts`
  - `web/src/app/app/crm/**/page.tsx`
  - `web/src/refresh-pages/Crm*.tsx`
- Timeline renderer: `web/src/app/app/message/messageComponents/timeline/renderers/crm/CrmToolRenderer.tsx`
- Tests:
  - `backend/tests/unit/onyx/db/test_crm_queries.py`
  - `backend/tests/unit/tools/test_crm_tool_packets.py`
  - `web/src/app/app/services/packetUtils.test.ts`
  - `web/src/app/app/message/messageComponents/timeline/hooks/packetProcessor.test.ts`

This is the baseline standard for future feature work.
