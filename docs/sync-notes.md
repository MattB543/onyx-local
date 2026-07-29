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
