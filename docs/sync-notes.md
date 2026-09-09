# Sync Notes — 2026-07-29 upstream sync (774 commits behind at start)

Rolling per-batch learnings for the sync from merge-base `c424edb511` toward `upstream/main`.
Fold stable patterns into `docs/git-sync-playbook.md` after the sync completes.

## Batch 1 — ec84e6efb1 (2026-07-29, 122 commits, 774→652 behind)

- Conflicts: 9 (8 content + 1 modify/delete). New files not in the recurring table:
  - `backend/onyx/onyxbot/slack/icons.py` — upstream replaced the if-chain with a
    `_SOURCE_IMAGE_FILENAMES: Mapping[DocumentSource, str]` dict + bare subscript
    (returns `str`, raises `KeyError` on unmapped sources). Fork-added
    `DocumentSource` members (GOOGLE_CALENDAR) must be added to the dict AND have
    their PNG in the new `web/public/slackbot-source-icons/` directory.
  - `backend/onyx/connectors/google_utils/resources.py` — upstream factored
    impersonation into `get_impersonated_creds()`; our Calendar service extends the
    return union. Both sides keep touching this file — expect re-conflicts.
  - `web/src/components/settings/lib.ts` — deleted upstream; live path is
    `web/src/lib/settings/svcSS.ts`. Our 404-tolerance guards were ported there
    (status !== 404 on enterprise-settings and analytics-script fetches).
    `SettingsError` enum is dead — dropped.
- Deviations from playbook defaults: none. Alembic heads merged per-batch
  (revision `f75baf85603b`) rather than deferred to post-sync.
- New upstream patterns:
  - `SECRET` → `USER_AUTH_SECRET` rename landed (app_configs, helm, env.template).
    Confirm prod `.env` uses the new name before next deploy.
  - `@onyx-ai/shared` / `@onyx-ai/opal` are workspace packages resolved through
    built `dist/`, not source. Verifying in a bare worktree needs real
    `node_modules` (or a tsconfig paths override to `lib/shared/src`), else tsc
    emits hundreds of phantom `ButtonProps` errors against a stale dist.
  - `web/package.json` changed (added highlightjs-sap-abap, dropped
    react-loader-spinner, several bumps) — reinstall deps before `next build`.
  - Fork-only `web/eslint.config.mjs` (import-x plugin, tseslint strict) means our
    eslint-disable comments conflict with upstream blank lines — recurring cosmetic
    conflict class.
- Orchestration learnings:
  - Agent worktrees branch from the session-start snapshot, NOT current main. If
    main has newer commits, `--ff-only` merge-back fails. Fix: each worktree
    agent's FIRST command is `git merge --ff-only main`; the orchestrator must
    also not commit to main while an implementation worktree is active.
    (Batch 1 recovered via: reset main to worktree branch, cherry-pick main's
    extra commits back on top — overlap was 2 files, clean.)
  - `scripts/sync-verify.sh` treated rc 2 as SKIP, but `tsc` exits 2 on type
    errors — a failing typecheck read as SKIP/0-failed. Fixed on main after
    batch 1.
  - Broken pyenv shim: bare `python` fails on this box; use `.venv/Scripts/python.exe`
    (sync-verify.sh does this via `$REPO_ROOT/.venv`).
- Codex sanity check: FAIL → fixed on main (ae5470d65f). Two findings:
  1. (blocker) The resources.py blend dropped upstream's `# ty: ignore[invalid-return-type]`
     comments on the five service getters — would fail upstream's `ty check` CI.
     Restored on all five (incl. our `get_calendar_service`). Lesson: when blending,
     preserve upstream's type-suppression comments even if the code reformats.
  2. (minor) GOOGLE_CALENDAR icon mapped to `Google.png`, but the Slack icon base URL
     serves from upstream's repo (raw.githubusercontent.com/onyx-dot-app/onyx/main),
     which has no Google.png → 404 in Slack. Remapped to upstream-hosted
     `GoogleDrive.png`. Fork-only sources must map to upstream-hosted filenames.
  Also from Codex: focused backend tests 125/125 pass; no leftover markers; alembic
  merge migration verified pure.

## Batch 2 — c86993bcd2 (2026-07-29, 1 commit isolated: refresh-pages/ → views/ rename, 652→651 behind)

- Conflicts: 30, ALL benign "CONFLICT (file location)" advisories — git's directory-rename
  detection auto-moved all 108 files (incl. our 30 fork-only CRM files) to `web/src/views/`
  with correct content. Resolution was a single `git add web/src/views/`. NO `git mv` needed —
  running one would have corrupted the index. Zero content conflicts.
- Also renamed: `web/src/ee/refresh-pages/` → `web/src/ee/views/` (no fork files there).
  `web/src/refresh-components/` NOT renamed — stays.
- Fork-side work: `@/refresh-pages/` → `@/views/` rewrites in 18 files (~65 occurrences:
  7 CRM route shims, 1 test, 10 self-references in moved files), jest.config.js testMatch
  globs (upstream FORGOT these — 4 suites incl. upstream's own InviteOnlyCard.test.tsx
  would have silently stopped running), e2e comment, 3 fork docs.
- Deviations from playbook defaults: none.
- Verification on main: jest 5 suites / 34 tests pass (suites confirmed executing);
  tsc 0 errors after `bun run build` in `web/lib/shared` (stale-dist phantom errors
  otherwise — 495 ButtonProps errors from a Jun 21 dist; rebuild before trusting tsc).
- Codex sanity check: PASS (all 30 fork files byte-preserved, route shims valid,
  jest globs verified, refresh-components intact, EE relocation counts match).

## Batch 3 — 11554205b8 (2026-07-29, 150 commits, 651→501 behind)

- Conflicts: 8 (4 content, 3 modify/delete, 1 rename+content). New files not in the
  recurring table:
  - `backend/onyx/db/chat.py` — looked like keep-ours but was dead reformatting;
    upstream's last-activity retention query (47475038f0) taken.
  - `web/src/lib/projects/svc.ts` + NEW `types.ts` — upstream extracted types; our
    `ProjectFile.attachment_source`/`index_for_later` fields ported into types.ts
    (TWO-file fix; marker-only resolution would silently break 6 consumer files).
  - `web/src/lib/userSS.ts` — deleted upstream, split into `web/src/lib/auth/svcSS.ts`
    + `auth/types.ts`. Our auth-type hardening (AUTH_TYPE_VALUES, resolveAuthType,
    buildFallbackAuthTypeMetadata, try/catch getAuthTypeMetadataSS) ported into
    auth/svcSS.ts. Future auth edits go there.
  - `web/src/components/MultiSelectDropdown.tsx` — deleted; react-select removed
    from package.json entirely. Do not resurrect.
  - `backend/ee/onyx/server/oauth/google_drive.py` — KEEP OURS (scope-sync via
    GOOGLE_SCOPES); upstream's only delta was a docs-URL comment.
- Deviations from playbook defaults: none. Alembic merge migration `fb9bb92cc072`
  (parents f75baf85603b + 2e0b2b146de1). Upstream added UserUsage/ModelCostOverride
  models+migration (no consumers yet — code lands in a later batch).
- New upstream patterns:
  - Span-replacement gotcha: when both conflict sides share a trailing suffix, git
    parks that suffix AFTER the last >>>>>>> marker — inspect ~5 lines past the
    marker before whole-span replacements (models.py near-miss).
  - Large web refactor: lib/user.ts→lib/users/svc.ts, hooks/useCurrentUser→
    lib/users/hooks.ts, lib/hooks/useProjects→lib/projects/hooks.ts,
    app/app/services/fileUtils→lib/projects/utils.ts. No fork dangling imports.
  - Stale `.next/` build artifacts caused 4 phantom tsc errors after upstream
    deleted routes (craft/v1/skills/manage) — `rm -rf web/.next` before trusting tsc.
  - Alembic DOES run from a worktree using the main checkout's venv python.
- Verification on main: sync-verify --batch all 7 PASS (tsc 0 after bun install +
  lib/shared rebuild + .next clear; CRM jest 34/34; backend custom suites green).
- Codex sanity check: PASS (models.py blend verified, chat retention AST-equivalent,
  auth fallback faithful, email triggers intact, alembic parents correct).

## Batch 4 — d318c47220 (2026-07-29, 49 commits, 501→452 behind)

- Conflicts: 10. Dominant theme: upstream's Google-credential architecture rewrite
  (07c235d978, 0aec0aa8f9, 12b6de9bdb) — app creds moved from KV store onto the
  credential row (`DB_CREDENTIALS_DICT_APP_CREDENTIAL_KEY`), 18 admin endpoints and
  6 google_kv.py functions deleted, `get_auth_url` +2 params, `build_service_account_creds`
  takes the key directly.
- DECISION (Option A, taken): ported our Google Calendar connector to the row-based
  flow instead of keeping a fork-local KV island. Frontend gcalendar pages rewritten
  from the merged gdrive equivalents (single-section auth UI, −~490 lines);
  `setupGoogleCalendarOAuth` now sends `google_app_credential` in credential_json;
  calendar service-account endpoint mirrors gdrive's. Existing prod Calendar
  credentials keep working (client id/secret ride in the stored token blob via
  upstream's `_app_cred_on_row` fallback; service-account keys already lived in
  credential_json). Old KV rows `google_calendar_*` are orphaned/harmless.
  USER-VISIBLE: Calendar admin setup UI is now the one-section flow (release note).
- Silent-break traps (no conflict markers): upstream's import deletions auto-merged
  while our code using them sat inside a conflict hunk (NameError trap); two
  signature changes broke auto-merged fork call sites (`get_auth_url` in our
  calendar authorize route, `build_service_account_creds` in our SA endpoint).
  Both fixed. LESSON: after big-deletion batches run RUFF, not just ast.parse —
  it also caught a leftover unused `current_admin_user` import.
- Cheap assertion for take-theirs-wholesale files: `git diff <upstream-sha> -- <file>`
  should be empty (credential.py verified byte-identical).
- Our batch-3 auth hardening in web/src/lib/auth/svcSS.ts survived upstream's
  requireAuth/requireAdminAuth move into the same file (import-union blend only).
- Alembic merge migration `a1c7d4e90b62` (parents fb9bb92cc072 + 8c8ff08f8035).
- DEPLOY FLAGS:
  1. Upstream migration `1fc2904131a3` (sso_provider seed) calls
     `encrypt_string_to_bytes` AT MIGRATION TIME — with our KMS envelope encryption,
     prod `alembic upgrade` needs KMS/SSM reachable IF the SAML/OIDC env-seed path
     fires (AUTH_TYPE=saml/oidc env config present with no existing row).
  2. Upstream switched model-server entrypoint to `python -m model_server` and
     dropped the DISABLE_MODEL_SERVER shell wrapper from compose — check whether
     the prod overlay still sets DISABLE_MODEL_SERVER (now a no-op).
- Verification on main: sync-verify --batch all 7 PASS.

- Codex sanity check (batch 4): 1 minor, no blockers. Finding: rewritten Calendar
  OAuth no longer sets GOOGLE_CALENDAR_AUTH_IS_ADMIN_COOKIE_NAME, so admins land on
  /user/connectors after OAuth. INVESTIGATED: upstream removed the cookie setters
  for ALL THREE Google connectors in this refactor — the callback route's cookie
  check is dead code upstream too; gmail/gdrive behave identically. DECISION:
  accept upstream parity, no fork-only fix (3-line patch possible later if the
  admin redirect is missed). Everything else PASS: payloads/scopes/API paths
  consistent, fork features intact, alembic verified.

## Batch 5 — 2ffae2fe02 (2026-07-29, 1 commit isolated: encrypted-KV table, 452→451 behind)

- Conflicts: only 2 (google_kv.py imports; store.py store()). The feared KMS collision
  was a NON-EVENT: upstream's new `encrypted_key_value_store.value` is an
  EncryptedJson column, which already routes through our KMS envelope primitives —
  zero changes to utils/encryption.py. Upstream's migration f6b0949ea33d is a pure
  SQL ciphertext copy (NO crypto at migration time, no KMS/SSM needed for alembic).
- Fork work: PgRedisKVStore.store() encrypt flag dropped (upstream shape taken);
  Unstructured API key relocated to encrypted_kv_store ({"value":...} wrap +
  unwrap_str) — ATOMIC with the store() change; ~10 fork regression tests
  retired/reframed; new structural test (test_encrypted_kv_no_cache.py, AST-based)
  locks "encrypted store has no cache path". load()'s encrypted_value fallback KEPT
  for pre-migration rows.
- LATENT FORK BUG FOUND: old encrypt=True write path for the Unstructured key
  raised TypeError (EncryptedJson requires dict, we passed str) — masked by an
  over-mocked test. Fixed by the relocation; no data migration needed (no valid
  row can exist). Deliberate contract call: delete_unstructured_api_key still
  PROPAGATES KvKeyNotFoundError (matches pre-existing endpoint behavior).
- Upstream bonus: 1h TTL + one-time-use on Google OAuth handshake state fixes the
  unbounded-CSRF-state regression our KMS commit had introduced. In-flight OAuth
  handshakes break across the deploy (restart flow; release note).
- DEPLOY FLAGS: (1) post-deploy, re-enter Unstructured API key in admin if used;
  (2) run reencrypt_secret_values.py dry-run post-deploy (auto-covers new table);
  (3) telemetry customer_uuid may regenerate if prod row was plaintext-only —
  precheck: SELECT key, value IS NOT NULL, encrypted_value IS NOT NULL FROM
  key_value_store WHERE key IN ('customer_uuid','instance_domain');
  (4) future upstream DROP COLUMN encrypted_value must remove our load() fallback
  + its test in the same change.
- Alembic merge migration c3b81de70f45 (parents a1c7d4e90b62 + f6b0949ea33d).
- Verification: worktree pytest 27/27 (KV + unstructured + google credential
  storage), ruff clean; main sync-verify --batch all 7 PASS.
- Codex sanity check: pending (batch qualifies as security-sensitive; per user
  policy Codex now runs ONLY on risky batches — mechanical batches skip it).
- Codex batch 5 verdict: BLOCKER (existing Unstructured API keys not migrated).
  Adjudication: partially right. Our fork's encrypt=True write path was broken
  post-KMS (TypeError), so no KMS-era row exists — but a PRE-KMS row (bare string,
  legacy Fernet/AES-CBC ciphertext readable via our decrypt fallback chain) could
  exist and would have been silently orphaned. Fixed on main: lazy read-repair in
  get_unstructured_api_key() (fallback to legacy kv row, migrate forward on first
  read, tolerate str or dict shapes). Codex's suggested pure-SQL ciphertext copy
  would have been WRONG — the legacy plaintext is a bare JSON string, not
  {"value": ...}; a byte copy would produce unwrap_str failures. All other
  security invariants independently verified by Codex: KMS files byte-unchanged,
  no secret writer on the cached path, handshake hardening + Calendar intact.

## Batch 6 — 9cdc575958 (2026-07-29, 150 commits, 451→301 behind)

- Conflicts: 14 (11 content, 3 modify/delete). Highlights:
  - Dockerfile.model_server TRAP: upstream moved installs into /app/.venv; keep-ours
    (--system) would ship an image with an empty venv. Blend = theirs' --python flag
    minus --require-hashes.
  - backend/onyx/utils/encryption.py: upstream added restore_masked_credentials
    (HARD BOOT DEP via sso_admin_router) — appended to our KMS module verbatim;
    kept our input_str spelling (upstream has intput_str typo; body uses ours).
  - web/src/lib/auth/svcSS.ts: hand-blended again (3rd batch in a row touching it);
    our fallback architecture + upstream's password-policy fields + sso_providers
    mapping; AuthType now imported from @/lib/auth/types NOT constants.
  - EmailPasswordForm/SignInButton moved into web/src/lib/auth/components.tsx;
    our type="email" ported. components/credentials/* moved to lib/credentials/*.
  - AppSidebar: upstream dropped wrapper div; crmButton re-inserted.
- Out-of-marker trap: @/hooks/useToast + ToastProvider moved into @opal/layouts —
  4 fork files (gcalendar Credential, CreateContactModal, CrmContactDetailPage,
  CrmOrganizationDetailPage) silently broken by auto-merge; fixed.
- ENVIRONMENT: upstream added readerwriterlock dep (installed into .venv);
  requirements/default.txt now pulls audioop-lts (Python>=3.13) — venv is 3.11.
  POST-SYNC TASK: check upstream's target Python + rebuild venv accordingly.
- ruff format --check fails repo-wide pre-existing (format vs lint); ruff CHECK is
  the gate. CRLF on disk — Python-script edits with \n patterns silently no-op.
- Alembic merge migration (parents c3b81de70f45 + b7e9a3c1d2f4) → head e4f7a2b91c08.
- Verification: worktree pytest 46/46 (KMS/ee/config/KV); main sync-verify --batch
  7/7 PASS after installing readerwriterlock.
- Codex batch 6 (focused review of 4 hand-blends): PASS — restore_masked_credentials
  composes with fork masking (no MASK_PREFIX dependency), svcSS mapping verified,
  Dockerfile venv coherent, tsc passed.

## Batch 7 — 4fe09b28d7 (2026-07-29, 64 commits, 301→237 behind)

- Conflicts: 5. Big theme: upstream REMOVED the AuthType enum + legacy
  single-provider SSO (9a9ad1e101, 577342f5cc, fa0287e2d2). svcSS.ts became a
  shape migration (AuthTypeMetadata: multiTenant replaces authType/autoRedirect);
  fork keeps only the never-throw fallback wrapper — file should be quieter now.
  AUTH_TYPE in docker-compose.prod-tunnel.yml is now inert/harmless.
- prompt-placeholder consolidation: handle_onyx_date_awareness deleted upstream;
  apply_prompt_placeholders gained our timezone kwarg (two-file fix:
  chat/prompt_utils.py + prompts/prompt_utils.py). Optional fork follow-up:
  thread timezone through process_prompt_template (4 llm_loop call sites) —
  NOT a regression, deferred.
- Out-of-marker trap: refresh-components/Modal + ConfirmationModalLayout moved
  into @opal/components / @opal/layouts — 6 fork CRM files silently broken;
  pure import swaps (APIs byte-identical).
- Known environmental failure: test_save_chat.py csv/TABULAR (Windows mimetypes
  registry) — already in the playbook's known-failures list; passes on Linux.
- Alembic merge migration f1a6d0c93b27 (parents e4f7a2b91c08 + 9cc89a7b96de).
- Verification: worktree pytest 514/515 (1 known env), ruff clean; main:
  sync-verify --batch 7/7 PASS, tsc 0 after bun install (45 new packages).
- Codex: skipped rename/format-class items; batch 6 focused review was PASS.

## Batch 8 — 46af76e98a + 9881c03822 (2026-07-29, 2 fmt commits isolated, 237→235 behind)

- Conflicts: 26, ALL pure import-block conflicts. Mechanical recipe worked:
  checkout --ours (semantic superset) → ruff --select I --fix + ruff format on
  the conflicted set, with upstream's new isort config (force-single-line and
  order-by-type removed) from the auto-merged pyproject.toml.
- Repo-wide fallout: the config change flagged 71 FORK-ONLY files (crm, custom
  jobs, calendar, ee encryption + tests) with I001 — import-sorted them too
  (--select I --fix only, NO repo-wide ruff format). New import style is
  multi-line-combined everywhere; future fork code should follow it.
- ruff format dirty-set shrank 70→63 files (strict subset — nothing newly
  dirtied). Pre-existing baseline issues noted: F811 duplicate
  TestGetBedrockAvailableModels in test_fetch_models_api.py (~line 1657) +
  12 F401s in alembic merge migrations — separate cleanup, not sync scope.
- embed_and_save.py will never be byte-identical to upstream (first-party
  resolution of `scripts` differs); ours is what repo-root ruff wants. Fine.
- No new migrations; single head f1a6d0c93b27 unchanged. Codex: skipped
  (mechanical batch, per policy).
- Verification: worktree pytest 181/181; main sync-verify --batch 7/7 PASS.

## Batch 9 — 4ea5da046c = upstream tip (2026-07-29, 235 commits, 235→0 behind. SYNC MERGE COMPLETE)

- Conflicts: 9. Key items:
  - chat_utils.py load_chat_file: upstream's lazy rewrite deleted the only call
    sites of fork-only chat_file_utils.py — fork fallback re-added under
    `if not user_file_id_str:` (raw uploads would have silently gotten
    token_count=0). ADD chat_file_utils.py to the recurring watch list.
  - Compose files are now GENERATED from docker-compose.template.yml
    (docker-compose-sync pre-commit hook; ods is a Go binary with no win32 wheel —
    hook no-ops locally but runs in CI). Our ONYX_VERSION args added to the
    template with `#!for prod,no-letsencrypt` scoping so the default variant and
    the embedded CLI copy (drift-tested) stay byte-identical. prod-tunnel.yml
    (fork-only) got `target: runtime` (dev stage is now the default last stage).
  - svcSS.ts: kept fork never-throw fallback + added REQUIRED passwordAuthEnabled
    (default true — otherwise password login vanishes when /auth/type hiccups).
  - env.prod.template: ours + upstream's commented legacy-SSO block. Env-based
    SSO deprecated, removal planned v4.5 — migrate prod to DB-backed SSO rows.
  - app_configs.py: upstream tenant-sharding block added (no-op unless
    ONYX_DB_SHARDS set). POSTGRES_HOSTS (ours) has zero consumers — candidate
    for removal.
- Alembic: final merge migration 563e4c5f4903 (parents f1a6d0c93b27 +
  f57f35403f6c); alembic_tenants separate single head b1c4e9d72f38 (multi-tenant
  only). NOTE: upstream migration 1e0a3e4226f7 calls encrypt_string_to_bytes at
  migration time — ONLY if llm_provider rows with provider='ollama_chat' exist.
  Pre-deploy check: SELECT id FROM llm_provider WHERE provider = 'ollama_chat';
  If rows exist, api_server needs KMS/SSM reachable at startup.
- DEPLOY FLAGS (batch 9 additions):
  - Runtime docker image lost curl/vim/nano/ps/psql (dev stage has them,
    published with -dev tag). Check prod runbooks/healthchecks that exec into
    api_server/background.
  - jest 29→30 + @types/jest 30, Storybook 8→10 (addon-essentials/blocks
    removed), oxfmt 0.59, ruff 0.16, dnd-kit sortable 8→10, azure blob deps new.
  - cryptography pin drift pre-existing: pyproject 46.0.5 vs requirements/uv.lock
    48.0.1 (Docker uses requirements → inert; reconcile later).
- Verification: worktree pytest 616/617 (1 known Windows env failure), ruff clean,
  all compose files parse + build blocks verified, rev-list vs upstream = 0.
- Codex batch 9 (final) verdict: PASS — all 9 resolutions verified, chat_utils
  token_count fallback flows correctly into ChatLoadedFile.lazy_loaded, compose
  scoping validated (default + embedded copies byte-identical), svcSS produces
  every required AuthTypeMetadata field on both paths, migration parents correct,
  all fork-feature spot-checks present.

## Batch 2026-08-03 — b87d5e1513 (single-batch, 80 commits)

- Conflicts: 0 (pure auto-merge; none of the recurring table files fired despite
  both sides touching llm_step/llm_loop/process_message — disjoint hunks)
- Deviations from playbook defaults: none. Stages 1-3 collapsed into one
  implementation agent (zero-conflict probe).
- Rode along with the sync: fork fix be0cc5db51 (explicit max_tokens for Claude
  models — Bedrock 4096-default truncation/EmptyLLMResponseError). Upstream
  954c514a7d + 374f2f1136 land MODEL_REFUSAL classification (closes the Opus 5
  refusal misdiagnosis; complements the max_tokens fix).
- New upstream patterns: 4 new migrations (heads merged in ebf99a6ad57e);
  Bifrost admin-selectable API mode (ad70f68e4c); license reclaim tasks (EE).
- Learnings:
  - Worktree base drift: the agent worktree branched 1 commit behind main and
    the "clean" merge silently dropped be0cc5db51 until the critical-file check
    caught it. Before merging in a worktree, assert
    `git merge-base --is-ancestor main HEAD`.
  - web/ has only bun.lock — `npm ci` fails; use `bun install --frozen-lockfile`.
  - test_litellm_monkey_patches.py::test_bridge_check_delegates_without_prefix
    fails on local venv (litellm 1.81.6 vs pin 1.93.0) — clears after venv
    rebuild; not merge damage.
- Codex sanity check: PASS (fix byte-intact, refusal integration coherent,
  25 targeted tests passed, alembic single head ebf99a6ad57e, imports OK).
  Noted stale playbook path: whitelabel logo now in web/src/lib/app/components.tsx
  (was refresh-components/Logo.tsx).

# Sync Notes — 2026-09-08 upstream sync (522 commits behind at start)

Merge-base `b87d5e1513` → `upstream/main` tip `5bf03a2c0f`. Backup branch
`pre-sync-backup-2026-09-08` (e1c7a8d161). Probe from start: N125=7, N150=11,
N200=18, N250=22, N350=23 (flat), N400=38, N450=49 (i18n extraction), N522=50.

## Batch 1 — 43e1bd4d6a (2026-09-08, 125 commits, 522→397 behind)

- Conflicts: 7 (exactly as probed). 1 fork-authored (`multi_llm.py`: Claude
  max_tokens be0cc5db51 + capacity backoff 6ea39ca4f0 vs upstream's Vertex
  stream-options rename 16a34b1fbd — blend; both sides verified present), 1
  semantic surprise (`web/next.config.js` — see deviations), 5 cosmetic
  take-theirs (`SandboxStatusIndicator.tsx`, `SearchUI.tsx`,
  `MCPAuthenticationModal.tsx`, `ChatUI.tsx`, `anonymous_chat.spec.ts`).
- Deviations from playbook defaults: `web/next.config.js` was assumed cosmetic
  but carries fork-only `allowedDevOrigins` (ngrok host) and `"mime"` in
  `transpilePackages` (4b17ea2b05). Promoted to the recurring table.
- New upstream patterns:
  - Cosmetic eslint-collision class: `SandboxStatusIndicator`, `SearchUI`,
    `MCPAuthenticationModal`, `ChatUI` all conflict solely because of fork
    commit b4a033ab62 (Feb 2026 eslint-disable / `memo` / `Record<string,never>`
    rewrites). Cheap signal: `git log --no-merges <merge-base>..main -- <file>`
    resolving to only b4a033ab62 ⇒ take theirs. Expect the same set again.
  - `/admin/settings` is now PATCH with partial-merge (#13266); fork
    `whitelabel_name` is env-forced on every `load_settings()` so unaffected.
  - EE extraction continues: `onyx/server/gateway/api.py` → `ee/...`, siblings
    (`models.py`, `configs.py`, `model_catalog.py`) stay CE. Watch for silently
    relocated sibling symbols in future batches.
  - alembic `merge heads` emits unused `op`/`sa` imports and the `black`
    post-write hook is broken in the venv (`Could not find entrypoint
    console_scripts.black`) — hand-clean each merge migration (ruff --fix +
    ruff format on the file). The 2026-08-03 migration `ebf99a6ad57e` carried 2
    F401s on main until this batch; fixed on main.
- Alembic merge migration `d03b8fbe9465` (parents a44c4ebac3d6 + ebf99a6ad57e).
- DEPLOY FLAGS: `a44c4ebac3d6` adds `file_record.file_size` with an
  `UPDATE … FROM file_content` backfill (full-table write, no crypto);
  aiohttp 3.14.3 + requirements bumps ⇒ venv rebuild; next 16.3.0, tailwind
  4.3.3, lucide 1.25; new optional env vars `CELERY_EXTERNAL_GROUP_SYNC_LOCK_TIMEOUT`,
  `IMAGE_SUMMARIZATION_TIMEOUT`, `CONTEXTUAL_RAG_LLM_TIMEOUT`,
  `ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED`/`OPENAI_GATEWAY_PASSTHROUGH_ENABLED`
  (default on); `ONYX_DB_SHARDS*` dropped from env.template (unused by fork).
- Verification: worktree pytest 972/973 (1 known Windows csv/TABULAR), ruff 0 new,
  web+backend import audit of fork-only files clean; main sync-verify --batch:
  7/7 PASS (tsc 0 after bun install + lib/shared rebuild + .next clear).
- Codex sanity check: skipped (mechanical batch; 1 blend already test-covered).

## Batch 2 — 97b67aab32 (2026-09-08, 225 commits, 397→172 behind)

- Conflicts: 17 (exactly as probed). 11 blends/keeps, 5 cosmetic take-theirs
  (`OptionItem`, `MCPLineItem`, `OpenApiActionCard`, `KickoffCSVExport`,
  `CreateStdOAuthCredential` — all b4a033ab62/a6d8239133-only, prediction held),
  1 inherited (`CreateStdOAuthCredential`).
- NEW RECURRING: `backend/onyx/auth/users.py` — KEEP OURS. Upstream deleted
  `current_admin_user` / `current_curator_or_admin_user` /
  `is_user_curator_or_admin` in favour of `require_permission(Permission.X)`;
  20+ fork-only call sites (crm/api.py, email_queue_api.py,
  manage/custom_jobs/api.py, auth_check.py, Calendar endpoints in
  documents/connector.py) still use the role shim. `UserRole` import re-added.
  STANDING DIVERGENCE — follow-up: migrate fork routes to `require_permission`
  to retire the shim (removes this recurring conflict).
- NEW RECURRING: `backend/onyx/server/documents/connector.py` — take upstream's
  import block, re-add `current_curator_or_admin_user` + `current_user` for the
  fork's Google Calendar SA-credential + callback endpoints.
- Deviations from playbook defaults: `web/src/lib/constants.ts` accepted upstream's
  removal of `TENANT_ID_COOKIE_NAME` (unsigned `onyx_tid` cookie dropped,
  ee51fcc2d6; zero consumers) while keeping the `*_AUTH_IS_ADMIN_COOKIE_NAME`s.
- `multi_llm.py` shrank: upstream upstreamed the `_anthropic_*` version helpers
  into `model_capabilities.py`; fork's local copies dropped. Fork delta is now
  just `_default_claude_max_tokens`/`auto_max_tokens` + degrade retry + backoff
  ladder; upstream's `request_params` recording parameterized on `max_tokens_arg`.
- OUT-OF-MARKER (new failure classes):
  1. Silent design-system rescale: f624117dce changed `<Section>` `gap`/`padding`
     from rem to numeric steps (N/4 rem) and ×4'd upstream call sites; fork-only
     call sites (gcalendar/Credential.tsx, CrmContactsPage/HomePage/
     InteractionsPage/OrganizationsPage, ChatPreferencesPage CRM block) had no
     conflict, no tsc error, no lint error — pure visual regression. 10 sites
     rescaled. RULE: after any `refactor(opal): …scale…` commit, diff every
     `gap=`/`padding=`/size-prop line in fork files against upstream's copy.
  2. Upstream widened `ruff select` (+B, +PERF): 8 violations, all in fork-only
     code (PERF401 in custom_jobs/registry.py, steps/*, db/crm.py ×2,
     db/reencrypt_secret_values.py; B905 `zip(strict=False)` in chat_files.py).
     RULE: run `ruff check backend/` right after the merge, before tests.
- Alembic merge migration `466166715a66` (parents d03b8fbe9465 + e7c00417d1e5);
  alembic_tenants head a754e4f72e60. No migration in this range runs crypto.
- DEPLOY FLAGS: `/health` is now pure liveness, readiness moved to
  `/health/ready` (226ec979bd) — prod compose healthchecks still resolve but
  gate earlier; consider `/health/ready` for api_server. New optional env:
  `MCP_SERVER_API_REQUEST_TIMEOUT_SECONDS`, `JWT_EXPECTED_AUDIENCE`,
  `JWT_EXPECTED_ISSUER`, `SALESFORCE_CLIENT_ID/SECRET`; JWT settings moved
  env→DB (cf085d9e2b) — verify `JWT_PUBLIC_KEY_URL` in env.config still honored.
  Deps: langfuse 3→4.14 (major), reportlab 5.0 new, ruff 0.16.1, onyx-devtools
  0.12.2 ⇒ venv rebuild; web: `@oxlint/plugins` new ⇒ bun install. Data
  migrations (bounded): 28bb08137807 SCIM username backfill + unique index,
  c8e316473aaa `user_role` nullable, c71a18ea7d07 is_manager flags,
  4d93b0fd5ca8 seed pinned assistants, f54501f1435a cost-budget normalize.
  `loadtest/`, `profiling/` moved to `tools/`.
- Verification: worktree ruff clean; pytest 4080 pass / 29 Windows-env fails
  (test_save_chat csv + 28 craft sandbox path/symlink tests — new known-noise
  set); targeted fork suites 263/263; main sync-verify --batch: 6/7 → 7/7 after 2 type-drift fixes (ae39d61758: Divider `paddingParallel="fit"` → `{0}`; `isCurator` → `hasAdminAccess` in CrmNav.tsx)
- Codex sanity check (astra low, focus on auth/users.py KEEP OURS + unified
  delete path + spacing rescale): ran during batch 3 — see addendum below.

### Batch 2 addendum — Codex sanity check (astra low): ISSUES → fixed on main

Codex verdict on 7261e1155a: 3 blockers + 1 should-fix. All three blockers verified
by reading code and fixed on main (commit after batch 3, see below):
1. (BLOCKER, startup) `auth_check.check_router_auth` accepts `current_admin_user`,
   `current_user`, and `require_permission` closures — but NOT
   `current_curator_or_admin_user`, which the fork's Calendar SA-credential route
   used → `RuntimeError` at api_server boot. Fix: route now uses
   `require_permission(Permission.MANAGE_CONNECTORS)` (parity with gmail/gdrive).
2. (BLOCKER, semantics) The kept role shim read `user.role`, which upstream turned
   into a nullable legacy tombstone (c8e316473aaa); admin grants now live in group
   membership → newly promoted admins would be locked out of CRM/custom-jobs
   routes, demoted legacy admins would keep access, and PAT token scopes were not
   enforced. Fix: `current_admin_user = require_permission(FULL_ADMIN_PANEL_ACCESS)`,
   `current_curator_or_admin_user = require_permission(MANAGE_CONNECTORS)` in
   `auth/users.py` (names kept so ~40 fork call sites + test dependency_overrides
   are untouched; `UserRole` import dropped). DECISION: "curator" mapped to
   MANAGE_CONNECTORS (used by CRM email-queue routes + Calendar). Full call-site
   migration to `require_permission` remains an optional follow-up; the shim is
   now semantically correct so the recurring conflict is the only remaining cost.
3. (BLOCKER, privacy) Fork `beginChatUpload` (raw `/api/chat/files/upload`) does
   not carry the incognito session id, so drag-drop uploads in an incognito chat
   escaped incognito cleanup. Fix: `useChatController` drop handler routes through
   upstream's session-aware `uploadFiles` when `incognitoEnabledRef.current`;
   `process_message.py` now rejects `index_for_later_file_ids` when the session's
   record mode does not persist content.
4. (SHOULD-FIX, inherited) `ProjectsContext`/`useChatController` list
   `incognitoUploadsEnabled` twice and omit `incognitoSessionId` from dep arrays —
   present verbatim in upstream 97b67aab32; left as-is to avoid conflict noise.
Codex verified correct: multi_llm request_params reflect the actual max_tokens
(incl. degrade retry), chat_utils fallback reachable, unified delete keeps
UserFile protection, 4 SearchDoc image sites, AppSidebar/WelcomeMessage/
ChatDocumentDisplay JSX, spacing rescale factor and coverage, 8 ruff changes
behavior-preserving, alembic parents, no markers, fork imports resolve.

## Batch 3 — 8ffe7b4093 (2026-09-08, 50 commits, 172→122 behind)

- Conflicts: 13, all frontend. 8 take-theirs (b4a033ab62-only), 2 take-theirs that
  were fork cherry-picks of upstream PRs (`MessageToolbar.tsx` 9947837f9f = #8582,
  `ParallelStreamingHeader.tsx` bc324a8070 = #8425 — always take theirs), 1
  modify/delete accepted (`web/src/lib/tools/openApiService.ts`, upstream
  reorganized lib/tools; won't recur), `toolDisplayHelpers.tsx` blend (CRM +
  Calendar `case` arms kept as literal strings next to upstream's `t("toolNames.*")`),
  `ChatPreferencesPage.tsx` in-marker take-theirs (CRM Settings block intact).
- Deviations from playbook defaults: none.
- OUT-OF-MARKER (large): upstream deleted `refresh-components/buttons/Button.tsx`
  (9597046bee). 14 fork files / 39 call sites migrated to `@opal/components`
  `Button` following upstream's own mapping: `main`→default, `action`/`danger`→
  `variant`, `secondary`/`tertiary`/`internal`→`prominence`, `leftIcon`→`icon`,
  layout `className`→wrapper div (Opal Button is WithoutStyles), icon-only
  children→`icon={({className,style}) => ...}` (must forward `style`),
  `!w-full justify-start`→`width="full"` + `[&_button]:justify-start` on parent.
  `IconButton`/`LineItem` survive. Rounding rescale (6bd66b856a): zero fork
  `rounding=` usages — no action. UserRole removal: frontend no-op.
- i18n: `NextIntlClientProvider` wraps root layout — fork routes need no wrapper.
  New oxlint `i18n/no-raw-jsx-text` is "error" on admin/sidebar/message globs that
  carry fork code. DECISION: rule exemption over translation keys — fork-local
  final override in `web/.oxlintrc.json` (gcalendar, CrmToolRenderer, AppSidebar
  CRM tab, ChatPreferences CRM block), because `src/i18n/messages/keyParity.ts`
  enforces exact key parity across en/de/es/fr/pt → every fork string would need
  5 catalogs. NEW STANDING DIVERGENCE; batch 4's i18n completion widens the globs
  → re-audit + extend the override.
- ruff C901 enabled (8e04d65c8c): 6 fork findings handled via upstream's own
  convention — `per-file-ignores` entries in `pyproject.toml` (google_calendar
  connector, db/crm.py, crm/api.py, crm_log_interaction_tool, crm_update_tool).
  NEW STANDING DIVERGENCE (alphabetically interleaved; small conflicts expected).
- Whitelabel (b0688f33a1): NO CHANGE. Upstream brands auth pages from EE
  enterprise-settings (`application_name`, custom logo); fork `whitelabel_name`
  rides the core settings endpoint which `/auth/*` skips. Login page still shows
  "Onyx" unless EE settings are configured — closing that is a new capability
  (expose whitelabel_name pre-auth), not a merge item. FOLLOW-UP CANDIDATE.
- Verification rig (reusable): worktree tsc works with tsconfig `paths`
  `@opal/*`→`./lib/opal/src/*` (source, no dist build) + `web/node_modules` as a
  real dir of per-entry junctions to main's node_modules, COPYING (not
  junctioning) packages the batch newly adds (junctions resolve React from the
  realpath → duplicate-React crashes). Never `bun install` against the junction.
  Do not run pytest and full jest concurrently (5s timeouts cascade).
- Alembic merge migration `cb4eb0dc83fd` (parents 466166715a66 + 66a70ddc0652).
- DEPLOY FLAGS: `next-intl` new runtime dep ⇒ `bun install` mandatory; locale via
  `NEXT_LOCALE` cookie, defaults en. Migration 66a70ddc0652 adds nullable
  `user.temperature_default`/`reasoning_effort_default` (no crypto/backfill).
  Backend deps: google-genai 1.52→2.18 (major), google-auth 2.57,
  google-cloud-aiplatform 1.165 ⇒ venv rebuild + Vertex/Gemini smoke test.
  Web: react-dropzone 14→20 (major).
- Verification: worktree tsc 0 (real run), jest 137 suites/1248 pass, ruff clean,
  pytest 3933 pass / 29 known Windows-env; main sync-verify --batch 7/7 PASS (with Codex batch-2 fixes applied; targeted pytest 2133 pass, tsc 0).
- Codex sanity check: skipped for batch 3 itself (mechanical UI migration,
  tsc-verified); Codex batch-2 fixes above landed on main in the same commit as
  these notes.

## Batch 4 — 94271d7e11 = upstream tip (2026-09-08, 134 commits, 122→0 behind. SYNC MERGE COMPLETE)

- Upstream moved 12 commits during the batch (planned target 5bf03a2c0f); merged
  live `upstream/main` instead — correct, since the goal is 0-behind. Re-probe
  against the live ref, not the planned hash.
- Conflicts: 15 (17 predicted). Key items:
  - `web/src/hooks/useAppFocus.ts` DELETED upstream (e71fc7f847) → fork `"crm"`
    position PORTED into `web/src/lib/position/hooks.ts`: `"crm"` in the
    parameterless `AppPositionType` arm, `hrefFor` case → `/app/crm`, `isCrm()`,
    `pathname.startsWith("/app/crm")` in `useAppPosition()`. AppSidebar's CRM tab
    (`activeSidebarTab.isCrm()`) auto-merged onto `useAppPosition()`. The playbook's
    `useAppFocus.ts` recurring row is retired; `lib/position/hooks.ts` replaces it.
  - `celery/apps/{heavy,primary}.py`: fork `tasks.custom_jobs` + upstream
    `tasks.capability_checks` (recurring blend for custom-jobs registration).
  - `useChatController.ts`: fork `beginChatUpload`/`uploadFiles` + incognito
    routing kept; upstream removed `useAgentPreferences`/`useForcedTools`
    (forced tool now lives in `toolConfiguration`, cbfd6b327b/e814627847).
  - `icons.tsx`: fork's icon superset (GoogleCalendarIcon, GmailIcon, …) kept +
    upstream `useTranslations` import; no phosphor on either side.
  - `auth/components.tsx`: fork `type="email"` + upstream i18n placeholder.
  - `InputComboBox.tsx`: `onClear`/`showAddPrefix` kept; upstream's un-defaulted
    `separatorLabel` taken (falls back to `t("separator.label")` at call sites).
  - `FinalStep`/`NameStep`/`ModifyCredential`: import-block blends (keep `memo`/
    `useMemo` still in use + upstream's `useTranslations`/`React`).
  - `AppPage.tsx` theirs (deleted `processSearchParamsAndSubmitMessage`);
    3 b4a033ab62-only cosmetic take-theirs.
- Deviations from playbook defaults: none.
- OUT-OF-MARKER: i18n ratchet widened to `src/**` (b65d5cc583) → 298 fork-only
  `no-raw-jsx-text` errors → `web/.oxlintrc.json` fork override extended to
  `src/app/app/crm/**`, `src/views/Crm*.tsx`, `src/views/crm/**`,
  `InputMultiSelect.tsx`, plus fork blocks in `OptionsList.tsx` ("Clear filter")
  and `sections/cards/FileCard.tsx` ("Index for later") → 0. New `ods check-getattr`
  pre-commit hook (8ddc6df49c): 8 fork-only `getattr` sites annotated
  `# ods: ignore[getattr]` (primary.py, google_utils/resources.py
  `RefreshableDriveObject`, db/crm.py ×5, exa_client.py, tests/utils/aws_secrets.py).
  NEW STANDING CONVENTION: every new fork `getattr` needs the marker; `ods` is a
  Linux-only binary so the hook can't run locally — CI verifies.
- Feature retirements: NONE. c9ca204db8 dropped only the local `unstructured`
  package; `unstructured-client` + API path stay, so the fork's encrypted-KV
  Unstructured API key handling + read-repair survive (tests pass). Lesson:
  check the *client* package before concluding a feature is gone.
- Checked clean: no rescale commits in range; appearance caps (50f46ffe96) hit EE
  `enterprise_settings` only, `whitelabel_name` unaffected; `multi_llm.py` fork
  block intact (upstream only extended the isolated-client set with Bedrock);
  `session_loading.py`/`tool_constructor.py`/`prompt_utils.py`/`llm_loop.py`/
  `process_message.py` and all CRM frontend files untouched by the merge.
- Alembic merge migration `1794c56fdb7c` (parents 287021f3b46c + cb4eb0dc83fd);
  schema_private head a754e4f72e60 unchanged.
- DEPLOY FLAGS: 4 new upstream migrations, NO crypto at migration time, no
  backfills; `287021f3b46c` adds nullable `voice_provider.api_secret` LargeBinary
  (encrypted at runtime via KMS envelope — KMS/SSM needed only when a voice
  provider is configured); `947b94d2ebf1` FK → ON DELETE CASCADE. Backend deps:
  `unstructured` REMOVED (+~23 transitive: langdetect, python-magic, gitpython,
  html5lib, emoji, filetype, …); extraction is Unstructured-API-only now → API key
  must be present in encrypted_kv_store for deployments that relied on local
  partitioning. Bumps: braintrust 0.3.9→0.37 (major), nltk 3.10.3, pypdf 6.16.1.
  Web: `@radix-ui/react-direction` new; react 19.2.8, next 16.3.3,
  react-icons 4→5 (major — fork icons.tsx uses FiCalendar/FaRobot/SiBookstack,
  type-clean, visual check advised). Env: `CODE_INTERPRETER_IMAGE_TAG` (optional),
  `OLD_INDEX_RECLAIM_ENABLED` (default true). RTL landed (7268c219a8): fork CRM
  CSS still uses physical ml-/mr- — cosmetic in RTL locales only.
- Verification (worktree): tsc 0 (real run; upstream tsconfig already maps
  `@opal/*` to source — no dist build needed), oxlint 0 i18n errors (4 pre-existing
  jsx-a11y on main), jest 142 suites/1300 tests at `--maxWorkers=3` (default
  workers → 7 spurious timeout failures; ALWAYS use `--maxWorkers=3`), ruff clean,
  pytest 9341 pass / 48 env (3 new diagnosed: gitbook fixture cp1252, HF
  tokenizer network, langfuse venv skew 3.10 vs 4.14.4 pinned). Main: see the
  post-sync section below.
- Codex sanity check: deferred to the whole-sync review (below).

## Post-sync (2026-09-08) — main at 0 behind upstream (94271d7e11)

- Dev venv rebuilt from pinned requirements (default+dev+ee; model_server.txt not
  installed → `model_server/test_embedding.py` ×2 fail on huggingface-hub 1.26 vs
  transformers' `<1.0` pin: env skew, fork does not touch model_server).
- `sync-verify.sh --full`: conflict markers PASS, commits behind 0, tsc 0,
  `next build` compiles, 5 fork feature suites PASS, ruff PASS, alembic single head
  (1794c56fdb7c), oxfmt SKIP (CRLF). Full unit tests: 9359 pass / 48 fail / 33 skip
  — all 48 environmental: the documented Windows set (simple_job_terminate ×2,
  save_chat csv, craft sandbox/session/nextjs_dev ×37, pptx docs, process_isolation
  ×2, sandbox_proxy ×2) + gitbook `test_parser_coverage_fixture` (upstream fixture
  opened without `encoding=` → cp1252) + model_server embedding ×2 (venv skew above).
  Secrets grep: hits are all upstream template defaults (`docker-compose.template`
  `${…:-minioadmin}`, `mint_api_key.sh` `ONYX_ADMIN_PASSWORD='...'`, ods regex test
  fixtures using `AKIAIOSFODNN7EXAMPLE`) — benign.
- Whole-sync Codex review (gpt-6-astra, MEDIUM): first attempt hit the usage limit
  after ~186k tokens (session 01a0838d-1da2-7a63-91b0-4885cbf65a50); resumed after
  the 10:18 PM reset — verdict recorded below when available.
- NOT PUSHED to origin yet.
