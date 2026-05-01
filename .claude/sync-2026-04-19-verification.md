# Upstream Sync Verification Brief — 2026-04-19

You are verifying a completed batched upstream sync for `MattB543/onyx-local`. Please check the work below for correctness. The fork was 515 commits behind upstream and is now fully caught up. All custom fork features should still be present and functional.

## What was done

Merged `onyx-dot-app/onyx` into `MattB543/onyx-local` in **11 batches** following `onyx-local/docs/git-sync-playbook.md`. Each batch used a 3-stage Opus agent pipeline (conflict analysis → user decision → implementation) in an isolated `git worktree`. Batches merged back to `main` via `git merge <worktree-branch>`, taking the worktree's version for overlap conflicts.

### Batch boundaries
| Batch | Target commit | Commits | Theme | Conflicts |
|---|---|---|---|---|
| 1 | `41ae039b` | 1–54 | Misc FE / opal refactors | 4 |
| 2 | `4bb6b76b` | 55–74 | **Dedicated Groups Phase 1** (AccountType/PermissionGrant schema) | 11 |
| 3 | `cf19d0df` | 75–124 | Bifrost gateway, multi-model schema start, Canvas scaffold | 16 |
| 4 | `009266e5` | 125–174 | Indexing refactor cluster (Iterable adapters) | 17 |
| 5 | `10d69626` | 175–224 | Multi-model backend, hook framework, Opal wave | 23 |
| 6 | `1c32a83d` | 225–274 | SidebarTab Opal v2, multi-model selector | 26 |
| 7 | `7ec50280` | 275–324 | Multi-model UI, auth role→account-type | 33 |
| 8 | `ef2df458` | 325–374 | Divider/Tooltip opalify, tabular indexing | 4 |
| 9 | `70fcfb1d` | 375–424 | DB session refactor (#10159), SWR_KEYS | 5 |
| 10 | `92bc13f9` | 425–474 | IMAP logger rename, trivial polish | 5 |
| 11 | `e9ab17de` | 475–515 | `/admin/configuration/llm` → `/language-models`, Opal polish | 1 |

### Safety
- Backup branches preserved: `pre-sync-backup` (this sync's starting HEAD), `pre-sync-backup-2026-03` (previous sync's HEAD)
- Nothing has been pushed — main is local-only until user reviews
- All 11 merge commits + alembic merge + 2 post-sync fix commits are on `main`

---

## Verification checklist

### 1. Sync completeness
```bash
cd C:/Users/matth/projects/onyx-test/onyx-local
git fetch upstream
git rev-list --count HEAD..upstream/main   # MUST be 0
git log -1 --oneline upstream/main          # should match an ancestor of HEAD
```

### 2. Alembic
```bash
cd backend
python -m alembic heads                     # MUST be exactly ONE head: 34e4e474896c
```
The sync created `backend/alembic/versions/34e4e474896c_merge_upstream_sync_2026_04_19.py` to unify our CRM migration chain with upstream's linear chain.

### 3. Frontend typecheck
```bash
cd web
rm -rf .next                                # clear stale Next.js type cache
npx tsc --noEmit                            # MUST exit 0 with 0 errors
```
If you see errors about `.next/dev/types/validator.ts`, you didn't clear `.next` — they're spurious.

### 4. Backend syntax (critical merged files)
```bash
cd C:/Users/matth/projects/onyx-test/onyx-local
python -c "
import ast
for f in [
    'backend/onyx/chat/process_message.py',
    'backend/onyx/indexing/adapters/document_indexing_adapter.py',
    'backend/onyx/connectors/google_utils/google_kv.py',
    'backend/onyx/connectors/imap/connector.py',
    'backend/onyx/db/models.py',
    'backend/onyx/db/chat.py',
    'backend/onyx/server/settings/store.py',
    'backend/onyx/server/documents/connector.py',
    'backend/onyx/auth/users.py',
    'backend/onyx/configs/app_configs.py',
]:
    ast.parse(open(f).read())
print('ALL OK')
"
```

### 5. Custom feature test suite
```bash
source .venv/bin/activate
python -m pytest \
  backend/tests/unit/onyx/db/test_crm_queries.py \
  backend/tests/unit/tools/test_crm_tool_packets.py \
  backend/tests/unit/onyx/server/features/test_crm_api.py \
  backend/tests/unit/onyx/utils/test_encryption.py \
  backend/tests/unit/onyx/configs/test_secret_encryption_config.py \
  backend/tests/unit/onyx/custom_jobs/ \
  backend/tests/unit/onyx/db/test_custom_jobs.py \
  backend/tests/unit/onyx/server/manage/test_custom_jobs_api.py \
  backend/tests/unit/onyx/indexing/test_email_trigger_emission.py \
  backend/tests/unit/tools/test_calendar_tool_packets.py \
  backend/tests/unit/onyx/db/test_calendar_queries.py
```
Expected: **266 passed**. Any new failure means a custom feature regressed.

### 6. Custom features present (sanity grep)
All of the following greps must return **non-zero counts**:

```bash
cd C:/Users/matth/projects/onyx-test/onyx-local

# CRM
grep -c "CrmAttendeeRole\|CrmContactSource\|CrmOrganizationType\|CrmInteractionType" backend/onyx/db/models.py
grep -c "href=\"/app/crm\"\|crmButton\|data-testid=\"AppSidebar/crm\"" web/src/sections/sidebar/AppSidebar.tsx
ls backend/onyx/db/crm.py                        # file exists
ls backend/onyx/tools/tool_implementations/crm/  # dir exists
ls web/src/refresh-pages/crm/                    # dir exists

# Whitelabel (3 sites)
grep -c "whitelabel_name\|whitelabelName" web/src/providers/DynamicMetadata.tsx
grep -c "whitelabelName" web/src/sections/sidebar/SidebarWrapper.tsx
grep -c "WHITELABEL_NAME\|whitelabel_name" backend/onyx/server/settings/store.py
grep -c "WHITELABEL_NAME" backend/onyx/configs/app_configs.py

# Email-CRM trigger emission (in indexing adapter)
grep -c "_emit_email_crm_trigger\|EMAIL_CRM_CUSTOM_JOB_ID" backend/onyx/indexing/adapters/document_indexing_adapter.py

# Custom jobs framework
grep -c "ENABLE_CUSTOM_JOBS\|custom_jobs_admin_router" backend/onyx/main.py
ls backend/onyx/custom_jobs/steps/ | wc -l       # must be >= 9 (9 step files)

# IMAP connector
ls backend/onyx/connectors/imap/                 # connector.py, models.py, __init__.py

# AWS KMS encryption
ls backend/onyx/utils/encryption.py backend/ee/onyx/utils/encryption.py
grep -c "EncryptedStringUnmasked" backend/onyx/db/models.py

# Google Calendar branches
grep -c "GOOGLE_CALENDAR\|KV_GOOGLE_CALENDAR" backend/onyx/connectors/google_utils/google_kv.py

# Timezone + index-for-later in process_message
grep -c "timezone=" backend/onyx/chat/process_message.py
grep -c "index_for_later_file_ids\|promote_chat_uploads_to_user_files\|enqueue_promoted_user_file_indexing" backend/onyx/chat/process_message.py

# Cloudflare Tunnel deployment
ls deployment/docker_compose/docker-compose.prod-tunnel.yml
ls deployment/docker_compose/env.ec2.cloudflare.template

# GHCR publishing
grep -c "ghcr.io\|ONYX_VERSION" .github/workflows/deployment.yml
```

### 7. No conflict markers anywhere
```bash
git grep -nE "^<<<<<<< |^=======$|^>>>>>>> " -- '*.py' '*.ts' '*.tsx' '*.js' '*.json' '*.yml' '*.yaml' '*.md' || echo "clean"
```
Should print `clean`. Any match means a conflict was left unresolved.

### 8. No secrets leaked
```bash
git diff origin/main..HEAD | grep -iE "AKIA|aws_secret_access|password=['\"]|-----BEGIN.*PRIVATE" | head
```
Should be empty. If anything non-trivial appears, investigate.

---

## Areas that got complex handling (audit these carefully)

### A. `backend/onyx/chat/process_message.py` (blended 4 times — batches 5, 6, 7, 9)
Upstream refactored this into a `ChatTurnSetup` generator pattern across several batches. Our custom additions that MUST still be present:
- Imports: `CacheBackend`, `enqueue_promoted_user_file_indexing`, `promote_chat_uploads_to_user_files`, `FileDescriptor`
- `promoted_user_file_ids` init + `index_for_later_file_ids` promotion block **before** `verify_user_files`
- `enqueue_promoted_user_file_indexing(...)` calls in both the USER-regen branch (with `db_session.commit()`) and the new-message branch (after `create_new_chat_message`)
- `timezone=setup.new_msg_req.timezone` kwarg on `run_llm_loop(...)` inside `_run_models`

Verify with: `grep -c "index_for_later_file_ids\|enqueue_promoted_user_file_indexing\|timezone=" backend/onyx/chat/process_message.py` — expect ≥ 3.

### B. `backend/onyx/indexing/adapters/document_indexing_adapter.py`
Upstream added `DocumentChunkEnricher` class; our fork has `_emit_email_crm_trigger_events` method. Both must coexist. `post_index` now takes `enrichment: ChunkEnrichmentContext` (renamed from `result: BuildMetadataAwareChunksResult`).

Verify: method present, class present, no conflict markers:
```bash
grep -c "_emit_email_crm_trigger_events\|class DocumentChunkEnricher" backend/onyx/indexing/adapters/document_indexing_adapter.py
```

### C. `backend/onyx/connectors/google_utils/google_kv.py` (blended in batch 9)
Upstream introduced `_load_google_json()` helper + `.model_dump(mode="json")` pattern. Our fork has `GOOGLE_CALENDAR` branches in 8 functions (`_build_frontend_google_drive_redirect`, `_get_current_oauth_user`, `get_auth_url`, `get_google_app_cred`, `upsert_google_app_cred`, `delete_google_app_cred`, `get_service_account_key`, `upsert_service_account_key`, `delete_service_account_key`). All Calendar branches must remain using the new helper/dump pattern.

### D. `web/src/sections/sidebar/AppSidebar.tsx` (blended in batches 6 + 7)
Upstream moved to `SidebarTab` Opal v2 API (PR #9866) with new `variant` prop + `AccountPopover`. Our CRM button (`crmButton` with `SvgOrganization` icon, `href="/app/crm"`, `activeSidebarTab.isCrm()`, `data-testid="AppSidebar/crm"`) must be inserted into the new structure. Expected render location: between `{searchChatsButton}` and `{isOnyxCraftEnabled && buildButton}` in the sidebar nav list.

### E. `web/src/sections/sidebar/SidebarWrapper.tsx` (blended 4 times)
Upstream rewrote LogoSection with `useMemo` for logo/closeButton + new padding. Our whitelabel-aware outer div sizing must survive:
- Outer div className: `cn("flex flex-row justify-between items-start pt-3 px-2", folded ? "justify-center" : "justify-between", (applicationName || whitelabelName) ? "h-[3.75rem] min-h-[3.75rem]" : "h-[3.25rem] min-h-[3.25rem]")`
- `applicationName` + `whitelabelName` destructured from `useSettingsContext()`

### F. `web/src/providers/DynamicMetadata.tsx`
**This file was rewritten by upstream multiple times (e.g., PR #9529 CSR migration) and silently dropped our whitelabel fallback.** The final state must have:
```tsx
const { enterpriseSettings, settings } = useSettingsContext();
// ...
const title = enterpriseSettings?.application_name || settings?.whitelabel_name || "Onyx";
```
Verify: `grep -c whitelabel web/src/providers/DynamicMetadata.tsx` ≥ 1.

### G. `web/src/refresh-pages/admin/ChatPreferencesPage.tsx` (blended 5 times)
Upstream did multiple layout/Opal rewrites around our CRM Settings section. Must preserve:
- `parseMultiLineValues` helper function
- `useCrmSettings` + `patchCrmSettings` imports
- CRM state (`crmStageOptionsRaw`, `crmCategorySuggestionsRaw`, `crmSaveInProgress`)
- CRM useEffect sync, `handleSaveCrmSettings`, `handleResetCrmSettingsToDefaults`
- "CRM Settings" `<SimpleCollapsible>` JSX block with two `<InputVertical>` (not `<InputLayouts.Vertical>` — that was a pre-existing bug fixed in batch 11) wrapping `<InputTextArea>` for stages + categories
- Save/Reset buttons

Verify: `grep -c "CRM Settings\|parseMultiLineValues\|useCrmSettings" web/src/refresh-pages/admin/ChatPreferencesPage.tsx` ≥ 3; `grep -c "InputLayouts.Vertical" web/src/refresh-pages/admin/ChatPreferencesPage.tsx` **must be 0**.

### H. `backend/onyx/db/models.py` enum import block
Upstream added `Permission`, `GrantSource`. Must be present alphabetically alongside our fork's `CrmAttendeeRole`, `CrmContactSource`, `CrmInteractionType`, `CrmOrganizationType`, `CustomJobRunStatus`, `CustomJobStepStatus`, `CustomJobTriggerEventStatus`, `CustomJobTriggerType`, `SyncType`, etc. No duplicates.

### I. `backend/onyx/server/settings/store.py`
Upstream added clamped upload-size logic (`DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB`, `MAX_ALLOWED_UPLOAD_SIZE_MB`). Must have **both** upstream's new logic AND our `settings.whitelabel_name = WHITELABEL_NAME` line.

### J. `backend/onyx/db/chat.py`
Upstream switched to `.tuples().all()` + `error_on_missing=False`. Our custom `raw_file_ids_to_consider` / `protected_raw_file_ids` / `plaintext_file_name_for_id` protected-file deletion logic must remain.

---

## Post-sync fixes added (not part of batch merges)

These are in commits `086fb14e7e` and `fda3ee8d6a`:

### Frontend (`086fb14e7e`)
- `web/src/app/admin/configuration/web-search/page.tsx` — replaced stale 1422-line fork version with upstream's 1-liner `export { default } from "@/refresh-pages/admin/WebSearchPage"` (all supporting files live under `web/src/refresh-pages/admin/WebSearchPage/` now)
- `web/src/refresh-components/Logo.tsx` — fixed undefined `foldedSize` → `resolvedSize` in whitelabel folded branch
- `web/src/providers/ProjectsContext.tsx` — replaced missing `DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB` (backend-only constant) with a fallback chain using `settings?.default_user_file_max_upload_size_mb` and hardcoded 100 MB
- `web/src/refresh-pages/Crm{Contacts,Interactions,Organizations}Page.tsx` + `crm/components/ActivityTimeline.tsx` — migrated `EmptyMessage` → `EmptyMessageCard` with `sizePreset="main-ui"`
- `web/src/refresh-pages/crm/components/{CreateContact,CreateOrganization,ImportCsv}Modal.tsx` — changed `Modal.Content width="md-sm"` → `"md"` (md-sm no longer in enum)

### Backend (`fda3ee8d6a`)
- `backend/onyx/configs/app_configs.py` — added back upstream constants that were dropped when we KEEP OURS'd: `MAX_CHUNKS_PER_DOC_BATCH`, `_POSTGRES_HOSTS_STR` + `POSTGRES_HOSTS`, `ONYX_SEARCH_UI_USES_OPENSEARCH_KEYWORD_SEARCH`, `VESPA_MIGRATION_SERVER_SIDE_REQUEST_TIMEOUT`
- `backend/onyx/auth/users.py` — added `current_admin_user` shim (upstream removed it in PR #9930 role→account-type migration, but our CRM + custom_jobs APIs still import it)
- `backend/onyx/server/documents/connector.py` — added missing imports for `current_admin_user` + `current_user` (they were used but not imported — latent from merge)
- `backend/tests/unit/tools/test_crm_tool_packets.py` — new `_TestBus` wrapper unwraps `(model_idx, packet)` tuples (Emitter now uses merge-queue per PR #9803); relaxed placement comparisons to ignore `model_index`
- `backend/tests/unit/tools/test_calendar_tool_packets.py` — same merge-queue unwrap
- `backend/tests/unit/onyx/indexing/test_email_trigger_emission.py` — switched `BuildMetadataAwareChunksResult` → `MagicMock(spec=ChunkEnrichmentContext)`, renamed kwarg `result=` → `enrichment=`; **deleted** `test_post_index_skips_trigger_for_non_allowlisted_sender_domain` (obsolete — adapter no longer filters by sender domain; see comment in `_emit_email_crm_trigger_events`)

---

## Known deferred work (NOT done in this session)

- **`uv.lock`** — kept ours throughout sync; needs `uv lock` regen before packaging a backend image
- **Push to `origin/main`** — local-only until user reviews
- **Playwright / integration tests** — require running services stack; not executed
- **`backend/tests/unit/onyx/auth/test_role_migration.py`** or similar — if the `current_admin_user` shim turns out to break account-type-based tests under specific paths, that's worth checking
- **Windows build quirks** — `npx next build` hits an NTFS colon issue per playbook (this is OS-level, not code)

---

## What to flag if you find anything

1. Any fork custom feature missing (see section 6 grep list)
2. Any conflict marker left in a tracked file
3. Any call to `current_admin_user` that isn't resolvable (would show as `NameError`)
4. The `EmptyMessageCard` migration — verify the CRM pages render (visual check) since API is slightly different from `EmptyMessage`
5. Any place where our `timezone` kwarg dropped off an LLM loop call (there are multiple LLM loop paths; the blend only preserved it on one)
6. Alembic: `python -m alembic heads` should be ONE revision, not two
7. If tsc shows any real errors (ignore `.next/` cache after `rm -rf .next`)

## Reference
- Playbook: `onyx-local/docs/git-sync-playbook.md`
- Previous sync backup: branch `pre-sync-backup-2026-03`
- This sync's starting HEAD backup: branch `pre-sync-backup`
- Current HEAD: run `git log -1 --oneline` — should be `fda3ee8d6a Post-sync fixes: restore missing constants, shim removed auth helpers, adapt tests`
