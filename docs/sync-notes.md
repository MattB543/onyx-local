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
