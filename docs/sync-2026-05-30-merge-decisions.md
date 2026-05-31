# Upstream Sync 2026-05-30 — Merge Decisions Digest

Independent audit context for a Codex reviewer. This captures EVERY conflict-resolution
decision made by the Opus merge agents across an 11-batch sync of `MattB543/onyx-local`
(fork) with `onyx-dot-app/onyx` (upstream). It exists so a reviewer can double-check the
RISKY integration points **without** re-reading all 508 commits.

## Sync summary
- Merged 508 upstream commits in 11 batches (~50 commits each).
- Merge-base (pre-sync): `85078e210d`. Upstream tip (now caught up): `2e8916566a`.
- Pre-sync fork HEAD / backup branch: `pre-sync-backup-20260530` @ `4fdb917352`.
- Post-sync: `git rev-list --count HEAD..upstream/main` == 0; 146 commits ahead; no conflict markers anywhere.
- Each batch: an Opus agent fast-forwarded a worktree to current main, merged the batch's
  incremental upstream target, resolved conflicts per the standing rules below, committed
  `--no-verify`, then we fast-forward-merged the worktree branch into main.

## The 8 custom fork features that MUST be preserved (audit these hardest)
1. **CRM module** — `backend/onyx/db/crm.py`, `backend/onyx/tools/crm/`, `web/src/refresh-pages/crm/`, `Crm*.tsx`, CRM API/server. 6 CRM tools + SearchCalendarTool registered in `backend/onyx/tools/built_in_tools.py`. `CRM_GUIDANCE` in `backend/onyx/chat/prompt_utils.py`. CRM elif blocks in `backend/onyx/server/query_and_chat/session_loading.py`.
2. **AWS KMS encryption** — `backend/onyx/utils/encryption.py`, `backend/ee/onyx/utils/encryption.py`. Encryption-aware caching in `backend/onyx/key_value_store/store.py` (encrypted values are NEVER cached in Redis). Pin: `cryptography==46.0.5` (upstream uses 46.0.7).
3. **Custom jobs framework** — `backend/onyx/custom_jobs/`, `backend/onyx/server/manage/custom_jobs/`, `ENABLE_CUSTOM_JOBS` import in `backend/onyx/main.py`. `EMAIL_CRM_CUSTOM_JOB_ID` in app_configs.
4. **Google Calendar connector** — `ValidSources.GoogleCalendar` + `DocumentSource.GOOGLE_CALENDAR` (+ description) in `backend/onyx/configs/constants.py` and `web/src/lib/types.ts`; `connectors.tsx`, `sources.ts`, cookie constants, callback route, tool construction.
5. **Email-to-CRM triggers / IMAP** — `backend/onyx/indexing/adapters/document_indexing_adapter.py` (`_emit_email_crm_trigger_events`, `EMAIL_CRM_CUSTOM_JOB_ID`, a `post_index` commit). `backend/onyx/connectors/imap/connector.py` (lookback_days/mailbox/retry logic). 7-day email retention controls.
6. **Deployment configs** — Cloudflare tunnel `deployment/docker_compose/docker-compose.prod-tunnel.yml`, `env.ec2.cloudflare.template`, EC2/bootstrap.
7. **Whitelabel branding** — `WHITELABEL_NAME` env vars, auth page server/client splits, `whitelabel_name` in `web/src/interfaces/settings.ts`, and a custom `useNativeType` prop on `web/src/refresh-components/inputs/PasswordInputTypeIn.tsx` (used by `EmailPasswordForm.tsx`).
8. **Timezone-in-chat + chat-upload** — `timezone` field in `web/src/app/app/services/lib.tsx` payload + `timezone` kwarg through `backend/onyx/chat/process_message.py`. Chat-upload: `verify_user_files`/`get_chat_upload_token_count`/`promote_chat_uploads_to_user_files` in `file_store/utils.py`, `chat_utils.py`, `process_message.py`. Custom file config: `FILE_TOKEN_COUNT_THRESHOLD`, `USER_FILE_MAX_UPLOAD_SIZE`, `SHOW_EXTRA_CONNECTORS`. Custom enums `ThemePreference`/`UserFileStatus`/`DefaultAppMode` + `Computed` import in `db/models.py`/`db/enums.py`.

## Standing resolution rules used by every agent
- **requirements/{default,dev,ee,model_server}.txt**: fork uses HASHLESS exports (`uv export --no-hashes`). Kept ours hashless, added new upstream deps hashless, preserved `cryptography==46.0.5`. Some batches regenerated via `uv export --frozen --no-hashes --group <g>` from the auto-merged `uv.lock`.
- **Frontend tooling**: upstream migrated eslint+prettier → **oxlint + oxfmt** (`.oxfmtrc.json` added, `.prettierignore` removed) and Python typing toward the **`ty`** checker. oxfmt-only reformatting and lint-config conflicts → took theirs.
- CRM / KMS / custom-jobs / Calendar / email-trigger / deployment / whitelabel / timezone code → **keep ours, integrate alongside** upstream (our code lives in separate elif/list branches or superset enums/constants).
- Non-CRM frontend, logging-style (f-string→lazy %), file moves/renames (refresh-components/→sections/, assistants/→agents/, Persona→Agent, @opal/components, eeGated→paidTierGated, ACP→sandbox) → **take theirs**; re-apply our customization in the new location if the moved file had any.
- DB models/migrations → keep BOTH sides; alembic heads merged at the end (see Open Items).

## Per-batch decisions

### Batch 1 — target d163ec8 (22 conflicts: 11 content + 11 modify/delete)
- `configs/constants.py` MANUAL BLEND: kept GOOGLE_CALENDAR enum+desc; accepted upstream removal of REQUESTTRACKER connector.
- `connectors/imap/connector.py` MANUAL BLEND: kept our try/finally + lookback_days + mailbox logic; adopted upstream lazy logging.
- `db/chat.py` take theirs (logging). `file_store/utils.py` MANUAL BLEND kept `verify_user_files`. `key_value_store/store.py` KEEP OURS (encryption-aware caching, never cache encrypted values). web_search clients take theirs (logging).
- `requirements/*.txt` (all 4) KEEP OURS hashless (cryptography 46.0.5 vs upstream 46.0.7). **Known divergence, not a defect.**
- 11 modify/delete: upstream removed admin embeddings/search UI routes — accepted deletion (no custom content).

### Batch 2 — target 738dcc0 (29 conflicts: 13 content + 16 modify/delete)
- NOTE: this worktree branched from the pre-sync base and merged cumulative #1-100; its resolved tree was adopted wholesale as a merge commit (tree verified identical, all custom features present). Subsequent batches switched to "FF to current main first" so they are strictly incremental.
- `configs/app_configs.py` MANUAL BLEND kept FILE_TOKEN_COUNT_THRESHOLD/USER_FILE_MAX_UPLOAD_SIZE/SHOW_EXTRA_CONNECTORS + added upstream QUERY_EMBEDDING_CACHE_ENABLED/_TTL_S.
- `imap/connector.py` KEEP OURS (nested mailbox fetch loop). `file_store/utils.py` KEEP OURS. `key_value_store/store.py` KEEP OURS (encryption caching).
- `web/src/refresh-pages/AgentEditorPage.tsx` take theirs (upstream replaced llm_model_*_override with default_model_configuration_id).
- 16 modify/delete: upstream removed admin embeddings/search routes + generic components — accepted.

### Batch 3 — target 6a16de9 (13 conflicts)
- `indexing/adapters/document_indexing_adapter.py` KEEP OURS email-CRM trigger block + `_emit_email_crm_trigger_events`; kept our post_index commit (upstream's new commits live in a separate auto-merged method — not a double-commit).
- `session_loading.py` MANUAL BLEND kept Crm* imports + added upstream CodingAgentFinal/Start. `built_in_tools.py` MANUAL BLEND kept CRM+SearchCalendar tools + added CodingAgentTool.
- `web/next.config.js` MANUAL BLEND kept "mime" transpile + adopted @onyx/opal→@onyx-ai/opal rename. Several frontend moves take theirs (Separator, SimplePopover, Persona→Agent rename in search/interfaces.ts).

### Batch 4 — target 868c204 (15 conflicts)
- `configs/constants.py` MANUAL BLEND re-added DocumentSource.GOOGLE_CALENDAR entry into upstream's improved DocumentSourceDescription dict.
- `requirements/default.txt` + `pyproject.toml` + `uv.lock` MANUAL BLEND kept cryptography 46.0.5 + added new upstream deps cron-descriptor/croniter (upstream's scheduled-tasks/cron feature).
- `web/src/app/globals.css` MANUAL BLEND re-applied our font-figure-small-label/value 12px/16px inside upstream's new @layer utilities.
- 9 modify/delete: upstream "craft"/WebSearchPage feature files removed — accepted.

### Batch 5 — target 2718289 (14 conflicts)
- Upstream REMOVED the old DocumentIndex interface (`interfaces.py`, `vespa/index.py`); our `document_indexing_adapter.py` auto-merged cleanly onto the new interface — email-CRM trigger block intact, no live imports of deleted modules.
- `requirements/default.txt`+`dev.txt` MANUAL BLEND hashless (added langchain-protocol; dropped upstream-removed black/reorder-python-imports + transitive). `context/search/models.py` take theirs (ty pragma).
- Several refresh-components: chose ours/theirs based on whether `React` is imported in-file (OverflowDiv KEEP OURS — uses bare HtmlHTMLAttributes; Button/IconButton/FieldMessage take theirs). `form/InputComboBoxField.tsx` KEEP OURS Omit list ("value"|"onChange"|"onValueChange"|"isError"). InputComboBox types.ts auto-merged with BOTH onClear + showOtherOptions.
- Upstream migrated frontend tooling eslint+prettier → oxlint+oxfmt this batch.

### Batch 6 — target db8506f (3 conflicts)
- `web/src/ce.tsx` take theirs (eeGated/EEComponent→paidTierGated/Component rename; verified no eeGated callers remain).
- `web/src/interfaces/settings.ts` MANUAL BLEND kept whitelabel_name + added is_containerized.
- `web/src/refresh-pages/admin/ChatPreferencesPage.tsx` MANUAL BLEND kept CRM imports (patchCrmSettings/useCrmSettings/DEFAULT_CRM_*) + added useTierAtLeast/Tier; dropped dead usePaidEnterpriseFeaturesEnabled import (upstream deleted source).
- OPEN ITEM: a stale ref to deleted `usePaidEnterpriseFeaturesEnabled` remains in `web/src/sections/modals/languageModels/CustomModal.test.tsx` (not in this batch's conflict set; may be cleaned by a later commit or surface in tsc).

### Batch 7 — target ccb88ad (9 conflicts)
- `db/models.py` MANUAL BLEND kept `from sqlalchemy import Computed` (used in 3 Computed() columns).
- `tests/unit/onyx/chat/test_chat_utils.py` MANUAL BLEND kept our token-count tests + upstream's new TestGetOrExtractPlaintext.
- `web/src/app/craft/hooks/useBuildSessionStore.ts` take theirs (dropped dead getBuildUserPersona import).
- modify/delete: `components/modals/EditPropertyModal.tsx` → upstream MOVE to sections/modals/; git rm, call sites already import new path.
- requirements: added docker/types-docker/types-paramiko/hyperframe, idna bump, cryptography 46.0.5 kept.

### Batch 8 — target b61f8b0 (8 conflicts)
- `requirements/*` REGENERATED via `uv export --frozen --no-hashes` from auto-merged uv.lock (30+ blocks were hash/new-dep noise). cryptography 46.0.5 preserved, hashless invariant held.
- `chat/process_message.py` MANUAL BLEND kept our chat-upload promotion block (promoted_user_file_ids/promote_chat_uploads_to_user_files); dropped a model_display_names parity block superseded by upstream's `_build_model_display_name(override, llm)` refactor (already applied at call site).
- `next.config.js` MANUAL BLEND kept "mime" + adopted upstream allowedDevOrigins ngrok dev config.
- `globals.css` MANUAL BLEND: upstream now ships typography via `@import "@onyx-ai/opal/root.css"`; re-added ONLY our two font overrides at 12px/16px in @layer utilities.
- `test_chat_utils.py` import union kept both load_chat_file + ChatLoadedFile/MessageType/ChatMessage.

### Batch 9 — target 3c1fd40 (10 conflicts)
- `chat/chat_utils.py` MANUAL BLEND: take theirs lazy-bytes `_extract` refactor; KEEP OURS get_chat_upload_token_count + estimate fallback.
- `web/src/refresh-components/inputs/PasswordInputTypeIn.tsx` MANUAL BLEND: adopted upstream prop renames (showClearButton→clearButton, rightSection→rightChildren, leftSearchIcon→searchIcon) + @opal/components import; **re-applied our custom `useNativeType`** (whitelabel auth, used by EmailPasswordForm.tsx:215).
- `craft/types/streamingTypes.ts` take theirs (ACP→sandbox rename). requirements regenerated hashless (cryptography 46.0.5).
- 3 modify/delete (opal separator, craft ToolCallPill/WorkingLine) accepted.

### Batch 10 — target 6b19d0d (6 conflicts) — has the one open visual item
- requirements all 4 REGENERATED via `uv export --frozen --no-hashes --group <g>`; default.txt 374→355 packages matching upstream (upstream regrouped deps; none lost). cryptography 46.0.5 kept.
- `web/src/refresh-components/Tabs.tsx` git rm (upstream MOVED Tabs into opal lib `web/lib/opal/src/components/tabs/`).
- **NOVEL (resolved, needs visual eyeball):** `web/src/refresh-pages/crm/CrmNav.tsx` — upstream moved Tabs to opal AND changed API: `variant` moved to Tabs root; Tabs/Tabs.List now use `WithoutStyles` (strips className/style); `rightContent`→`rightChildren`. Our CRM nav passed a custom className for transparent pill backgrounds. Agent migrated the import, moved variant to root, renamed the prop, and re-applied the transparent-bg overrides via a WRAPPER `<div>` using `[&_.opal-tabs-list]` / `[&_[role=tab]]` descendant selectors. Functionally equivalent; visual styling now depends on opal's `.opal-tabs-list` class name → **eyeball CRM nav appearance in the running app.**

### Batch 11 (final) — target 2e8916566a / upstream tip (1 conflict)
- `requirements/default.txt` MANUAL BLEND hashless: added python-docx==1.1.2, dropped orphan pypandoc-binary==1.16.2 (upstream replaced pandoc with mistune+python-docx in new `server/features/build/session/md_to_docx.py`; pypandoc-binary unreferenced in merged pyproject/uv.lock). All recurring-conflict files auto-merged cleanly; customizations verified present.
- CAUGHT_UP verified == 0.

## OPEN ITEMS for verification (not yet done at time of writing)
1. **Alembic multiple heads + DUPLICATE revision** — `alembic heads` shows 3-4 heads (17cfc2b66463, 4d545225fd82, a5370af8f8a0, b6c7d8e9f0a1) AND warns "Revision b6c7d8e9f0a1 is present more than once". Deploy blocker — must dedupe the colliding revision id and `alembic merge heads` into one head.
2. **CrmNav.tsx** transparent-pill styling (Batch 10) — visually verify in the running app.
3. **Dangling ref** to deleted `usePaidEnterpriseFeaturesEnabled` in `web/src/sections/modals/languageModels/CustomModal.test.tsx` — confirm removed or fix.
4. **Frontend type drift** — run `npx tsc --noEmit` in web/, categorize ours-vs-upstream, fix ours (expect import-path/component-prop/enum drift per playbook).
5. **Custom-feature unit tests** — run and confirm green:
   - CRM: `backend/tests/unit/onyx/db/test_crm_queries.py`, `backend/tests/unit/tools/test_crm_tool_packets.py`, `backend/tests/unit/onyx/server/features/test_crm_api.py`
   - KMS: `backend/tests/unit/onyx/utils/test_kms_encryption.py`, `backend/tests/unit/ee/onyx/utils/test_encryption.py`, `backend/tests/unit/onyx/configs/test_secret_encryption_config.py`
   - Custom jobs: `backend/tests/unit/onyx/custom_jobs/`
   - Calendar: `backend/tests/unit/tools/test_calendar_tool_packets.py`
   - Email triggers: `backend/tests/unit/onyx/indexing/test_email_trigger_emission.py`
6. **Highest-risk integration points to re-read** (where upstream structurally refactored AND our code integrates): `document_indexing_adapter.py` (DocumentIndex interface removal, Batch 5), `process_message.py` (model-display-name refactor, Batch 8), `chat_utils.py` (lazy-bytes _extract, Batch 9), `built_in_tools.py`/`session_loading.py` (tool dispatch + CodingAgent additions), `key_value_store/store.py` (encryption-aware caching survived upstream cache-write changes).
