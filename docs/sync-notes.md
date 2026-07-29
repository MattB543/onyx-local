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
