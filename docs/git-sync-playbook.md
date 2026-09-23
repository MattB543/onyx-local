# Playbook: Batched Upstream Sync for onyx-local Fork

## Overview

This playbook documents how to sync MattB543/onyx-local with onyx-dot-app/onyx when 100+ commits have accumulated. It was developed and refined during a 438-commit sync across 9 batches (completed March 2026), a 774-commit sync (July 2026), a 522-commit sync in 4 batches (September 2026), and a 216-commit sync in 4 batches (2026-09-23, ~15-50 min per batch).

The approach: merge upstream in adaptively-sized batches (conflict-budget probing, ~25-100 commits) using a staged Opus agent pipeline per batch, with human decision-making between analysis and implementation, and an advisory Codex sanity check after each batch lands.

## When to Use This Playbook

- Fork is 50+ commits behind upstream
- Running `git rev-list --count HEAD..upstream/main` returns a large number
- You want to preserve all custom fork features while catching up

## Pre-work

### 1. Safety snapshot

```bash
git branch pre-sync-backup   # snapshot before anything starts
git fetch upstream            # ensure we have latest
```

### 2. Assess the gap

```bash
git rev-list --count HEAD..upstream/main          # commits behind
git rev-list --count upstream/main..HEAD          # commits ahead
git diff --name-only HEAD...upstream/main | wc -l # files changed by both sides
```

### 3. Identify custom fork commits

```bash
# List commits ahead of upstream (our custom work)
git log --oneline upstream/main..HEAD
```

Categorize each commit as:

- **Genuinely custom** (CRM, KMS, deployment, etc.) — must preserve
- **Cherry-picks of upstream** — accept upstream's version (canonical source)

### 4. Refresh the custom features table

The "Custom Fork Features" table at the bottom of this playbook goes stale between syncs. Launch a cheap read-only agent to diff `upstream/main..HEAD`, compare against the table, and report additions/removals — update the table before the first batch.

### 5. Plan batch boundaries (adaptive sizing)

Don't use a fixed batch size — probe conflict density and let it set the boundary. `git merge-tree --write-tree HEAD <target>` performs an in-memory merge and reports conflicted files without touching the working tree, so probing is cheap:

```bash
MERGE_BASE=$(git merge-base HEAD upstream/main)
COMMITS=$(git rev-list --reverse ${MERGE_BASE}..upstream/main)

# Probe candidate batch endpoints at 25/50/75/100 commits out
for N in 25 50 75 100; do
  TARGET=$(echo "$COMMITS" | sed -n "${N}p")
  [ -z "$TARGET" ] && break
  CONFLICTS=$(git merge-tree --write-tree HEAD $TARGET 2>/dev/null | grep -c "CONFLICT" || true)
  echo "batch of $N commits → ~$CONFLICTS conflicts (target: $(git log --oneline -1 $TARGET))"
done
```

Pick the **largest batch that stays under a conflict budget of ~15 conflicted files**, then adjust:

- **Align boundaries with major PRs** — don't split a large refactor across batches
- **Isolate high-risk changes** — give major reworks (e.g., LLM provider refactor, component library migration) their own batch, even if the probe says the conflict count is low
- Low-conflict stretches can merge in one 100-commit batch; a hairy refactor should shrink to its own small batch

Historical reference: the 438-commit sync used fixed 50-commit batches with 4-65 conflicts per batch — the probe would have merged the quiet stretches faster and split the two worst batches.

## Per-Batch Workflow: Staged Agent Pipeline

### Computing the target commit

Re-run the conflict probe from Pre-work step 5 to pick this batch's size, then:

```bash
MERGE_BASE=$(git merge-base HEAD upstream/main)
TARGET=$(git rev-list --reverse ${MERGE_BASE}..upstream/main | sed -n "${BATCH_SIZE}p")
git log --oneline $TARGET -1  # verify
```

After each batch merges, `MERGE_BASE` advances automatically — always recompute (including the probe; conflict density changes as the merge-base moves).

---

### Stage 1: Conflict Analysis Agent (Opus, isolated worktree)

Launch an Opus agent with `isolation: "worktree"` to attempt the merge and report conflicts.

**Agent prompt should include:**

- Target commit hash
- List of known recurring conflict files with resolution patterns (see below)
- List of custom fork features to flag

**What the agent does:**

1. Runs `git merge <target> --no-edit` in the worktree
2. Lists all conflicted files (`git diff --name-only --diff-filter=U`)
3. For each conflict: shows both sides, explains the change, recommends resolution
4. Notes auto-merged files that touch custom features
5. Aborts the merge (`git merge --abort`)
6. Returns a conflict report

**Output:** Per-file recommendations (KEEP OURS / TAKE THEIRS / MANUAL BLEND).

### User Decision Point

Review the conflict report. For each file:

- Approve the recommendation, OR
- Override with different instructions
- Add notes for tricky blends

**Pro tip:** For batches with <10 conflicts and familiar patterns, skip straight to Stage 3 with the approved recommendations — Stage 2 (separate planning agent) adds overhead without value for simple merges. Stages 2+3 can be collapsed into a single implementation agent.

### Stage 2: Merge Plan Agent (Opus) — optional for simple batches

Only needed when conflicts require complex blending (e.g., structural refactors, API changes).

**What it does:**

1. Reads both versions of each conflicted file
2. Writes exact merged code for "manual blend" files
3. Checks cross-file consistency (imports, types, model fields)

### Stage 3: Implementation Agent (Opus, isolated worktree)

**Agent prompt should include:**

- Target commit hash
- Complete resolution instructions for every conflict
- Categorized file lists: manual blend files first, then "take theirs" bulk list, then modify/delete files

**What the agent does:**

0. Asserts the worktree is not behind main: `git merge-base --is-ancestor main HEAD` (2026-08 sync: a worktree branched 1 commit behind main produced a "clean" merge silently missing the newest fork commit). If it fails, `git reset --hard main` first.
1. Runs `git merge <target> --no-edit` in the worktree
2. Resolves manual blend conflicts first (reads files, applies precise edits)
3. Bulk-resolves "take theirs" files: `git checkout --theirs <file>`
4. Handles modify/delete conflicts: `git rm <file>` for accepted deletions
5. Stages everything: `git add -A`
6. Verifies no conflict markers: `grep -r "<<<<<<< " --include="*.py" --include="*.ts" --include="*.tsx" .`
7. Commits: `git commit --no-edit`
8. Ends its report with a **Learnings** section: new conflict files not in the recurring table, resolutions that deviated from the playbook defaults, upstream patterns worth knowing. The orchestrating session appends this to the sync notes (see below) — the agent must NOT write the notes file itself from the worktree.

### Merging Worktree Back to Main

The worktree branch already contains main's history (it branched from main), so adopting it is a fast-forward — no merge conflicts to resolve:

```bash
git merge --ff-only <worktree-branch>
```

If `--ff-only` fails, main moved during the batch (e.g., a sync-notes commit landed). Either rebase the worktree branch onto main first, or — since `pre-sync-backup` exists — inspect what moved and use `git reset --hard <worktree-branch>` if main's extra commits should be discarded. Do NOT fall back to a normal merge and hand-resolve overlap conflicts; the worktree's tree is always the correct result.

**Note:** If pre-commit hooks are slow, `--no-verify` is fine on any commit made here — the code was already verified in the worktree.

### Sync notes (per-batch learnings)

Keep a rolling `docs/sync-notes.md`. After each merge-back, the orchestrating session appends one section on main:

```markdown
## Batch N — <target-commit-short-hash> (<date>)

- Conflicts: <count> (<files not already in the recurring table>)
- Deviations from playbook defaults: <what and why, or "none">
- New upstream patterns: <API/structure changes future batches will hit>
- Codex sanity check: <PASS or issues found + how fixed>
```

This is appended on main only (never from a worktree) so the notes file can't itself become a merge conflict between worktrees. After the full sync, fold any stable patterns from the notes into this playbook's "Recurring Conflict Files" and "Conflict Resolution Defaults" tables.

### Stage 4: Codex Sanity Check (advisory, runs in parallel)

After each batch lands on main, launch Codex (via the `codex-as-subagent` skill, read-only) to independently review the merge. A non-Claude model catches correlated blind spots an Opus reviewer shares with the Opus implementer.

**Run it concurrently with the next batch's Stage 1 analysis** — verifying batch N doesn't block analyzing batch N+1, so it adds ~zero wall-clock time.

**Give it:**

- The batch's merge commit (`git show <merge-commit> --stat`) plus full diffs of the files that had conflicts
- The resolution decisions made (which files were KEEP OURS / TAKE THEIRS / MANUAL BLEND)
- The "Custom Fork Features" table from this playbook

**Ask it to check:**

- Leftover conflict markers
- Custom features dropped or half-merged (e.g., a "take theirs" that deleted a CRM elif branch)
- Resolutions that look wrong given both sides' intent
- Import/type breakage in the touched files

**Output:** a structured verdict — PASS, or a list of issues each with file, problem, and suggested fix.

**Codex is advisory only — it never edits files.** If it flags something real, the orchestrating session (or a Stage 3-style agent) applies the fix on main, keeping one writer per batch. The next batch's analysis then recomputes from the corrected merge-base (the "always recompute MERGE_BASE" rule already handles this). Record the verdict in the sync notes.

### Cleanup after each batch

```bash
git branch -D <worktree-branch>           # delete the worktree branch
git rev-list --count HEAD..upstream/main   # verify progress
```

---

## Recurring Conflict Files

These files conflict in nearly every batch because our fork adds code in the same regions upstream modifies. The resolution pattern is stable:

| File                                                    | Our addition                    | Resolution                                                                                                                                                            |
| ------------------------------------------------------- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/onyx/tools/constants.py`                       | CRM + Calendar tool IDs         | **KEEP OURS + add new upstream IDs.** Our version is a superset. Just append any new upstream constants (e.g., `MEMORY_TOOL_ID`).                                     |
| `backend/onyx/db/models.py`                             | CRM enums in import block       | **MANUAL BLEND.** Keep our enums (`ThemePreference`, `UserFileStatus`, `DefaultAppMode`) + add any new upstream enums (`SharingScope`, etc.).                         |
| `backend/onyx/chat/prompt_utils.py`                     | `CRM_GUIDANCE` in tool guidance | **MANUAL BLEND.** Upstream uses a list-based `tool_sections` pattern. Add `CRM_GUIDANCE` to the list. Keep `timezone` param. Verify the `CRM_GUIDANCE` import exists. |
| `backend/onyx/server/query_and_chat/session_loading.py` | CRM tool elif blocks            | **MANUAL BLEND.** Keep our CRM/Calendar elif blocks alongside upstream's new tool blocks (e.g., PythonTool). They're separate branches — no overlap.                  |
| `backend/onyx/main.py`                                  | `ENABLE_CUSTOM_JOBS` import     | **MANUAL BLEND.** Keep our import + add any new upstream imports (`CACHE_BACKEND`, `DISABLE_VECTOR_DB`, etc.).                                                        |
| `web/src/lib/position/hooks.ts` (was `hooks/useAppFocus.ts`, deleted upstream 2026-09) | `"crm"` app position | **MANUAL BLEND.** Keep `"crm"` in the parameterless `AppPositionType` arm, the `hrefFor` case -> `/app/crm`, `isCrm()`, and the `pathname.startsWith("/app/crm")` branch in `useAppPosition()`. `AppSidebar.tsx` CRM tab calls `activeSidebarTab.isCrm()`. |
| `web/src/app/app/services/lib.tsx`                      | `timezone` in chat payload      | **MANUAL BLEND.** Keep both `timezone` (ours) and `additional_context` (theirs) in the payload. Import conflict: take theirs.                                         |
| `web/src/lib/auth/svcSS.ts`                             | Never-throw auth-metadata fallback | **MANUAL BLEND.** Blended in 5 of 9 batches of the 2026-07 sync. Keep our `buildFallbackAuthTypeMetadata` + try/catch `getAuthTypeMetadataSS`; add any new upstream `AuthTypeMetadata` fields to BOTH the fallback and the success path (required fields break tsc silently otherwise). |
| `backend/onyx/chat/chat_utils.py`                       | Raw chat-upload token counting  | **MANUAL BLEND.** Fork-only `chat_file_utils.py` provides `get_chat_upload_token_count`/`estimate_token_count_for_text`; upstream refactors of `load_chat_file` tend to delete its call sites — re-add the `if not user_file_id_str:` fallback or raw uploads silently get token_count=0. |
| `web/next.config.js`                                    | `allowedDevOrigins` (ngrok host) + `"mime"` in `transpilePackages` | **MANUAL BLEND.** Take upstream's file, then re-add both fork entries (commit 4b17ea2b05). Looks cosmetic in the probe but is not. |
| `backend/onyx/llm/multi_llm.py`                        | Claude `max_tokens` + capacity backoff | **MANUAL BLEND.** Fork delta is `_default_claude_max_tokens`/`auto_max_tokens` (fills in ONLY when the caller passes `max_tokens=None` — never cap caller-set values; upstream's chat loop passes its own context-aware allowance since #14605), the `BadRequestError` -> `_run_attempts(None)` degrade retry (auto value only), and the `_is_quota_exhaustion`/`LLM_SERVICE_UNAVAILABLE_*` ladder. Upstream's reasoning-none learning loop nests inside `_run_attempts` (`nonlocal reasoning_effort`). Upstream's `request_params` recording must reflect the actual `max_tokens_arg`. Check whether upstream has upstreamed a fork helper before blending (the `_anthropic_*` helpers moved to `model_capabilities.py` in 2026-09). |
| `backend/onyx/file_store/utils.py`                      | Per-chat file scoping in `verify_user_files` | **MANUAL BLEND.** Upstream hardens file-reference validation here (#14824, 2026-09). Take every upstream check (unparseable `user_file_id` rejected; existing user file must be owned AND match the descriptor id) and keep the fork's raw-chat-upload / project fallback for descriptors without a `user_file_id`. Security-sensitive — get a Codex review. |
| `backend/onyx/tools/tool_implementations/web_search/clients/google_pse_client.py` | Web search result image extraction | **MANUAL BLEND.** Keep fork image extraction on the same (encoded, timeout-bounded) response upstream fetches. |
| `web/src/lib/connectors/credentials.ts`                 | `google_calendar` credential type + template | **MANUAL BLEND.** Looks b4a033ab62-only in `--no-merges` history but carries fork Calendar code from merge commits. Add the fork entries to upstream's `CredentialTemplateMap`. |
| `web/src/hooks/useChatController.ts`, `web/src/views/AppPage.tsx` | Chat fork ("Branch from here"), raw chat uploads, incognito drop handling | **MANUAL BLEND.** Keep `onBranchFromMessage` (incl. `toolConfigurationRef.current.handOffTo(newSessionId)` so branches inherit per-chat filters/tool states), pending prefill, `initialMessageKey`, raw uploads + index-for-later, incognito `beginUpload`+`setCurrentMessageFiles`. |
| `web/src/app/app/services/streamingModels.ts`, `.../timeline/hooks/packetProcessor.ts` | CRM/Calendar packet types (enumerated in 6 frontend files + `session_loading.py`) | **MANUAL BLEND.** Usually import-block only; keep every fork packet type/branch. |
| `web/src/i18n/messages/*.json` (9 locales) + connector catalog `SOURCE_DESCRIPTION_KEYS` | `googleCalendar` source description (after `gmail`) + chat-fork `branch.*` keys | **KEEP OURS + take upstream keys.** Every fork `ValidSources` member needs a catalog description key or tsc fails; `keyParity` needs the key in all 9 files (catalogs are CRLF in this checkout). |

| `backend/onyx/auth/users.py`                            | `current_admin_user` / `current_curator_or_admin_user` | **KEEP OURS.** Since 2026-09 these are `require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)` / `require_permission(Permission.MANAGE_CONNECTORS)` aliases (NOT role checks: `User.role` is a nullable tombstone upstream). ~40 fork call sites (CRM, custom jobs) + test `dependency_overrides` depend on the names. Follow-up to retire: migrate call sites to `require_permission` directly. |
| `backend/onyx/server/documents/connector.py`            | Google Calendar SA-credential + callback routes | **MANUAL BLEND.** Take upstream's import block; fork routes use `require_permission(Permission.MANAGE_CONNECTORS)` (parity with gmail/gdrive) and `current_user`. Any dependency not accepted by `auth_check.check_router_auth` fails api_server startup. |
| `backend/onyx/background/celery/apps/{heavy,primary}.py` | `tasks.custom_jobs` registration | **MANUAL BLEND.** Keep the fork include alongside upstream's new task modules. |
| `web/.oxlintrc.json`, `pyproject.toml` `per-file-ignores` | i18n `no-raw-jsx-text` fork override; C901 fork entries | **KEEP OURS + take upstream additions.** Fork strings are exempt from i18n (5-locale `keyParity.ts` makes catalog keys impractical); extend the override when upstream widens the ratchet globs. |

## Conflict Resolution Defaults

These guide the analysis agent's recommendations:

| Category                       | Default                                 | Notes                                                                |
| ------------------------------ | --------------------------------------- | -------------------------------------------------------------------- |
| CRM module (models, tools, UI) | Keep ours, integrate alongside upstream | Our code sits in separate elif/list branches                         |
| KMS encryption                 | Keep ours entirely                      | Upstream doesn't touch this                                          |
| Custom jobs framework          | Keep ours                               | `ENABLE_CUSTOM_JOBS` in main.py, task registration in celery workers |
| Google Calendar connector      | Keep ours                               | Cookie constants, callback route, tool construction                  |
| Deployment configs             | Keep ours                               | Tunnel, bootstrap, EC2 — separate files from upstream                |
| Frontend components (non-CRM)  | Take theirs                             | Upstream does major UI refactoring regularly                         |
| DB models/migrations           | Keep both sides                         | Merge Alembic heads afterward                                        |
| Cherry-picked commits          | Accept upstream's version               | They're the canonical source                                         |

## Post-Sync Fixes (expect these every time)

After all batches merge, there will be integration drift to fix:

### 1. Frontend type drift in custom pages

Our CRM/Calendar pages reference component APIs that upstream changed. Common fixes:

- **Import paths:** `assistants` → `agents`, `refresh-components/` → `sections/`, `@opal/components` migration
- **Component props:** `Button disabled={x}` → `<Disabled disabled={x}><Button>`, `width="xl"` → `width="lg"`, removed props like `titleIconInline`
- **Type changes:** upstream dropped `MinimalUserSnapshot.full_name` — our fork deliberately RE-ADDS it (`backend/onyx/server/models.py`, `full_name=u.personal_name` in `users.py`); keep ours. Other enum members dropped/renamed: follow upstream
- **Missing enum members:** `ValidSources.GoogleCalendar` may get lost — re-add it along with `GoogleCalendarConfig` and source map entry

**Fix process:** Run `npx tsc --noEmit`, categorize errors as ours vs upstream, fix only ours.

### 2. Backend import breakage

Upstream refactors can break import chains through our custom code. Watch for:

- Functions renamed or removed during refactors (e.g., `cleanup_legacy_kv_store_redis_cache` dropped during CacheBackend refactor)
- New abstraction layers replacing direct calls (e.g., `CacheBackend` replacing raw Redis)

**Fix process:** Run the custom feature test suite, trace any `ImportError` through the chain, re-add or adapt the missing symbols.

### 3. Alembic dual heads

If upstream added migrations and we have our own, there will be multiple Alembic heads. This is a deploy blocker.

```bash
cd backend && python -m alembic heads           # check for multiple heads
python -m alembic merge heads -m "merge_upstream_sync_heads"  # create merge migration
python -m alembic heads                          # verify single head
```

### 4. Test mock drift

Upstream may change method signatures (e.g., adding `.unique()` to query results) that break our test mocks. Fix by updating mocks to match new signatures.

### 5. Formatting/linting

Run prettier on modified custom files, ruff on modified Python files. These are cosmetic but should be clean before pushing.

## Verification Checklist (before pushing)

Keep this as a runnable script (`scripts/sync-verify.sh`) so agents and the Codex checker can execute it mechanically — per batch for the cheap checks (tsc, custom-feature pytest), and in full before pushing.

Known baseline (as of 2026-07-29, ruff-clean tree):

- `ruff check backend/` must run from the **repo root** — the per-file-ignores in `pyproject.toml` are rooted there and silently stop matching if run from inside `backend/`. The script does this correctly.
- Fork code is ruff-clean; a nonzero ruff result after a sync means the merge introduced it. Exception class: `alembic merge heads` emits unused `op`/`sa` imports and the `black` post-write hook is broken in the venv — run `ruff check --fix` + `ruff format` on each new merge migration.
- On the Windows dev box, ~30 unit tests fail for environmental reasons (symlinks/POSIX file modes, signals, Docker, mimetypes registry, cp1252 default encoding) — in `test_simple_job_terminate.py`, `test_save_chat.py` (csv/TABULAR), `test_confluence_checkpointing.py`, `sandbox_proxy/`, `server/features/craft/sandbox/` (sandbox_daemon, safe_extract, docker_manager_config), `utils/test_process_isolation.py`, `skills/test_pptx_skill_docs.py`. As of 2026-09-23 the set is **67** (10,954 pass, ~26 min): add `server/features/craft/` (`test_outputs_manifest`, `test_nextjs_dev`, `session/test_webapp_info`), `connectors/zoom/` (18 — Windows `OSError [Errno 22]` in `cross_connector_utils/miscellaneous_utils.py`), `connectors/test_connector_download_limits.py` (2 — POSIX `0o600` modes), `connectors/gitbook/test_gitbook_parsing.py` (fixture read as cp1252). Failures **outside** that set are real regressions. (`ee/server/log_export/test_log_collection.py` is excluded by the script — `os.geteuid` at collection time aborts the whole run on Windows.)
- Web formatting is `oxfmt` (upstream dropped prettier 2026-07); the check only works on LF checkouts, so the script skips it on Windows — CI is the real gate.
- `web/` has only `bun.lock` (no package-lock.json) — `npm ci` fails; install with `bun install --frozen-lockfile`.
- Always run jest with `--maxWorkers=3` (default worker count manufactures ~7 spurious timeout failures) and never concurrently with pytest.
- Local `oxlint` needs `NODE_OPTIONS=--experimental-strip-types` (its `.ts` plugins); `ods check-getattr` (Linux binary) cannot run locally — annotate fork `getattr` calls with `# ods: ignore[getattr]` by convention.
- `ruff format --check backend/` is not a gate (72 pre-existing repo-wide diffs); `ruff check` is. `alembic merge heads` leaves unused imports (broken `black` hook) — `ruff check --fix` + `ruff format` the new file.
- Worktree tsc: `@opal/*` resolves from source via tsconfig `paths`; build `web/node_modules` as a real dir of per-entry junctions to main's, COPY (not junction) newly added packages. Never `bun install` against the junction.
- After any `refactor(opal): ...scale...` commit, diff every `gap=`/`padding=`/`rounding=` line in fork files against upstream's copy — silent visual regressions produce no conflict, tsc, or lint signal.
- After a batch, run `ruff check backend/` BEFORE tests: upstream widening `select` (B, PERF, C901 in 2026-09) lands violations only in fork-only code.
- Cosmetic-conflict signal: `git log --no-merges <merge-base>..main -- <file>` resolving to only `b4a033ab62` (Feb-2026 eslint/memo rewrites) or the cherry-picks `9947837f9f`/`bc324a8070` means TAKE THEIRS — but ALWAYS also read `git diff <merge-base> main -- <file>`: fork code that arrived via earlier merge commits is invisible to `--no-merges` (2026-09-23: `credentials.ts` carried the Calendar template). Consider reverting b4a033ab62's cosmetic hunks to stop the recurring noise (~70% of the 2026-09-23 conflicts were b4a033ab62-only).
- Agent-tool worktrees are created at **origin/main**, not local main — step 0 of Stage 3 (`merge-base --is-ancestor main HEAD`, else `git reset --hard main`) fired in every batch of the 2026-09-23 sync.
- Per batch, run only the fork suites + the specific test files for blended areas (target ~15-20 min/batch). Broad directory sweeps (`tests/unit/onyx/connectors`, `server`, `redis`…) sit idle for minutes on Windows socket timeouts and look hung; the full unit suite (~22 min) runs once at the end with `-o faulthandler_timeout=300`.
- Set `LITELLM_LOCAL_MODEL_COST_MAP=True` for pytest: litellm's live price list drops legacy models and flips fork/upstream tests.
- Removed-kwarg class: upstream deletes "dead" parameters that only fork callers still pass (2026-09-23: `bypass_acl` → email→CRM TypeError on every run), and mocked fork tests hide it. After each batch, grep fork code for params removed in the range.
- tsc on main between `bun install`s: web pins a TS 7 nightly; until main is re-installed, run `node node_modules/typescript-7/bin/tsc -p tsconfig.json --noEmit`. Delete `.next/dev/types` + `.next/types` first — stale typed-route files produce false `RouteImpl`/`Cannot find module .../page.js` errors after upstream moves routes.

```
[ ] git rev-list --count HEAD..upstream/main  → 0
[ ] npx tsc --noEmit                          → 0 errors (or only upstream errors)
[ ] npx next build                            → compiles (Windows NTFS colon issue is OS-level, not code)
[ ] python -m pytest backend/tests/unit/ -v   → all pass
[ ] python -m ruff check backend/             → clean (or only pre-existing upstream issues)
[ ] npx prettier --check "src/**"             → clean on custom files
[ ] python -m alembic heads                   → single head
[ ] git diff origin/main..HEAD | grep -iE "AKIA|aws_secret|password=" → no real secrets
[ ] Custom features functional: CRM, KMS, Calendar, custom jobs, deployment
```

## Lessons Learned

### What worked well

- **Conflict-budget batch sizing** — probe with `git merge-tree` and take the largest batch under ~15 conflicted files. (The original sync used fixed 50-commit batches, which ranged 4-65 conflicts; adaptive sizing smooths that out.)
- **Isolated worktrees** for implementation agents — safe to attempt merges without affecting main
- **Collapsing stages 2+3** for simple batches saved significant time
- **Consistent conflict resolution patterns** — the same ~8 files conflict every batch with the same resolution, making later batches faster
- **`--no-verify` on merge commits** — pre-commit hooks can hang on large merges; verification was done in the worktree

### What to watch out for

- **Merge-back should be a fast-forward** — if `--ff-only` fails, main moved during the batch; figure out what moved rather than hand-resolving overlap conflicts. The worktree's tree is always the correct result.
- **`.claude/worktrees/` directories** get accidentally staged by `git add -A` — ensure `.gitignore` covers them
- **Modify/delete conflicts recur** for files upstream deleted — accept deletion and `git rm` each time until they stop appearing
- **Codex review per non-trivial batch pays off** — 2026-09-23: it caught a merge-introduced behavior change (caller-set Claude max_tokens cap), a security regression in a fork feature (branched chats dropping per-chat search filters), and the anonymous-persona break in email→CRM; none had a conflict marker or test failure.
- **Upstream file moves confuse git** — files moved from `refresh-components/` to `sections/` or `assistants/` to `agents/` cause rename-tracking conflicts. Take theirs.
- **EE endpoint hardening** — after sync, `fetchEnterpriseSettingsSS` and `fetchCustomAnalyticsScriptSS` may need `response.ok` guards and 404 tolerance for non-enterprise deployments
- **`LICENSE_ENFORCEMENT_ENABLED=false`** should be set in dev scripts to match backend behavior

### Timing

2026-09-23 (216 commits, 4 batches, one session): batch 1 ~50 min (full unit suite run per batch — don't), batch 2 ~36 min (broad test sweep sat on socket timeouts), batches 3-4 ~16 / ~22 min under the narrow per-batch test rule. Codex reviews (astra medium, ~10-15 min each) ran concurrently with the next batch.

The full 438-commit sync took ~3 sessions across 2 days:

- Batches 1-6: first session (analysis + implementation per batch, ~45 min each)
- Batches 7-9: second session (~30 min each, patterns were established)
- Post-sync fixes: ~2 hours (type drift, test failures, alembic, formatting)

## Custom Fork Features (must preserve in every sync)

Refresh this table before each sync (Pre-work step 4) — diff `upstream/main..HEAD` and reconcile against it.

| Feature            | Key files                                                                                                                               | How to verify                                                                                                                                                     |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CRM module         | `backend/onyx/db/crm.py`, `backend/onyx/tools/tool_implementations/crm/`, `backend/onyx/server/features/crm/`, `web/src/views/crm/`, `web/src/views/Crm*.tsx`, `web/src/app/app/crm/`, `web/src/lib/hooks/useCrm*.ts`, `web/src/app/app/message/messageComponents/timeline/renderers/crm/CrmToolRenderer.tsx` | `pytest backend/tests/unit/onyx/db/test_crm_queries.py backend/tests/unit/tools/test_crm_tool_packets.py backend/tests/unit/tools/test_crm_list_tool.py backend/tests/unit/onyx/server/features/test_crm_api.py` |
| AWS KMS encryption | `backend/onyx/utils/encryption.py`, `backend/ee/onyx/utils/encryption.py` (note: `tests/unit/ee/.../test_encryption.py` is upstream-owned; our fork test is `test_kms_encryption.py`) | `pytest backend/tests/unit/onyx/utils/test_kms_encryption.py backend/tests/unit/ee/onyx/utils/test_encryption.py backend/tests/unit/onyx/configs/test_secret_encryption_config.py` |
| Secret encryption at rest (KV) | `backend/onyx/key_value_store/store.py`, `backend/onyx/db/reencrypt_secret_values.py`, `backend/onyx/configs/app_configs.py`, `backend/onyx/file_processing/unstructured.py`, migration `a1d4f89ce352` | `pytest backend/tests/unit/onyx/key_value_store/ backend/tests/unit/onyx/configs/test_secret_encryption_config.py backend/tests/unit/onyx/file_processing/test_unstructured.py` |
| Custom jobs        | `backend/onyx/custom_jobs/`, `backend/onyx/server/manage/custom_jobs/`, `backend/onyx/background/celery/tasks/custom_jobs/`, `backend/onyx/db/custom_jobs.py`, our entries in `backend/onyx/background/celery/tasks/beat_schedule.py` | `pytest backend/tests/unit/onyx/custom_jobs/ backend/tests/unit/onyx/db/test_custom_jobs.py backend/tests/unit/onyx/server/manage/test_custom_jobs_api.py`        |
| Google Calendar    | `backend/onyx/connectors/google_calendar/`, `backend/onyx/db/calendar.py`, `backend/onyx/tools/tool_implementations/calendar/`, `web/src/lib/googleCalendar.ts`, `web/src/lib/types.ts` (ValidSources.GoogleCalendar), `web/src/lib/connectors/connectors.tsx`, `web/src/lib/sources.ts`, `web/src/app/admin/connectors/[connector]/pages/gcalendar/`, callback route `web/src/app/admin/connectors/[connector]/auth/callback/route.ts`, GOOGLE_CALENDAR scope block in `backend/onyx/connectors/google_utils/shared_constants.py` | `pytest backend/tests/unit/tools/test_calendar_tool_packets.py backend/tests/unit/onyx/db/test_calendar_queries.py backend/tests/unit/onyx/connectors/google_calendar/test_connector.py` |
| Email triggers     | `backend/onyx/indexing/adapters/document_indexing_adapter.py`, `backend/onyx/custom_jobs/steps/fetch_email_trigger_payload.py`          | `pytest backend/tests/unit/onyx/indexing/test_email_trigger_emission.py`                                                                                          |
| Email-to-CRM pipeline + Email Queue tab | `backend/onyx/custom_jobs/workflows/email_crm_processor.py`, `backend/onyx/custom_jobs/steps/process_email_crm.py`, `backend/onyx/server/features/crm/email_queue_api.py`, `web/src/views/CrmEmailQueuePage.tsx`, `web/src/lib/hooks/useCrmEmailQueue.ts`, `web/src/app/app/crm/emailQueueService.ts` | `pytest backend/tests/unit/onyx/custom_jobs/test_email_crm_workflow.py backend/tests/unit/onyx/custom_jobs/test_email_crm_steps.py` — runs the chat pipeline headless as `get_anonymous_user()`; since upstream #14671 the anonymous user needs the persona public AND listed, and `bypass_acl` is gone (#14943) |
| Email retention (7-day IMAP window) | `backend/onyx/connectors/imap/connector.py`, `backend/onyx/db/custom_jobs.py`, `web/src/lib/connectors/connectors.tsx`, `web/src/app/admin/connectors/[connector]/pages/ConnectorInput/NumberInput.tsx`, `.../pages/FieldRendering.tsx` | `pytest backend/tests/unit/onyx/connectors/imap/test_imap_connector.py backend/tests/unit/onyx/db/test_custom_jobs.py` |
| CRM policy fields + category taxonomy | `backend/onyx/db/crm.py`, `backend/onyx/db/models.py`, `backend/onyx/prompts/tool_prompts.py`, `backend/onyx/server/features/crm/models.py`, `backend/onyx/server/features/crm/csv_utils.py`, `web/src/views/crm/crmOptions.ts`, migration `d4061bb581a7` | `pytest backend/tests/unit/onyx/db/test_crm_queries.py backend/tests/unit/onyx/server/features/test_crm_api.py backend/tests/unit/tools/test_crm_list_tool.py` (asserts `party_affiliation`/`us_state`/`principal`) |
| CRM `updated_at` = last activity (DB triggers) | Migration `39db7165c7ac` (a BEFORE UPDATE stamp trigger on `crm_contact` / `crm_organization` / `crm_interaction`, plus AFTER triggers on tags, owners, interactions, attendees and org membership; attendee `user_id` FK changed to `ON DELETE CASCADE`; index `ix_crm_interaction_attendee_contact_interaction`), matching `CrmInteractionAttendee` changes in `backend/onyx/db/models.py` | `pytest backend/tests/external_dependency_unit/crm/` against a database migrated with `alembic upgrade head` (the fixture fails if the triggers are missing). Upstream never touches these tables; on rebase keep the revision at the head of the fork chain |
| Strict CRM AI tools (no silent drops) | `backend/onyx/tools/tool_implementations/crm/` (`validation.py`; `crm_update` `add_tag_ids`/`remove_tag_ids` and `updated`/`no_changes`; unknown fields rejected; `crm_create` `not_applied_fields` and `warnings`; owners by teammate email; one transaction per call; honest attendee confidence; `crm_list` rejects inapplicable/malformed filters; `page_size` max 25 in `crm_list`/`crm_search`; `crm_get` include checks; owner, org, attendee and logger names via `CrmNames` in `models.py`), `backend/onyx/db/crm.py` (bool tag helpers, diff-based `replace_interaction_attendees`, `find_assignable_users_by_email`, attendee-aware `list_interactions` with id tie-breaker, batch name lookups), refresh in `post_interaction` (`backend/onyx/server/features/crm/api.py`). UI effect: contact and org timelines include attendee-only interactions | `pytest backend/tests/external_dependency_unit/crm/` (migrated DB) plus the CRM module unit tests above |
| Built-in tool seeding (CRM + Calendar) | `backend/onyx/tools/built_in_tools.py`, `backend/onyx/tools/constants.py`, `backend/onyx/tools/tool_constructor.py`, `backend/onyx/server/query_and_chat/session_loading.py`, seed migrations `b6c7d8e9f0a2`, `d7e8f9a0b1c2`, `f5b6c7d8e9f0` | `pytest backend/tests/unit/tools/test_built_in_tools_registry.py` |
| Chat file scoping (per-chat uploads) | `backend/onyx/chat/chat_file_utils.py`, `backend/onyx/server/query_and_chat/chat_files.py`, `backend/onyx/file_store/utils.py`, `web/src/providers/ProjectsContext.tsx` | `pytest backend/tests/unit/onyx/chat/test_chat_file_utils.py backend/tests/unit/onyx/server/query_and_chat/test_chat_files.py backend/tests/unit/onyx/chat/test_chat_utils.py backend/tests/unit/onyx/db/test_chat_deletion.py backend/tests/unit/file_store/test_utils.py backend/tests/unit/onyx/access/test_user_file_access.py` |
| Web search result images | `backend/onyx/context/search/models.py`, `backend/onyx/tools/tool_implementations/web_search/clients/`, `backend/onyx/db/chat.py`, `backend/ee/onyx/server/query_and_chat/models.py`, migration `b7e3a1f09c42` | `pytest backend/tests/unit/onyx/tools/tool_implementations/websearch/ backend/tests/unit/onyx/db/test_chat_search_doc_image.py backend/tests/unit/ee/onyx/server/query_and_chat/test_models.py` |
| Chat answer persistence fix | `backend/onyx/chat/process_message.py` (commit 393aa6252b) | No test — the fallback persisting completed answers with empty `answer_tokens` must not be reverted; a "take theirs" here silently restores the "terminated prior to completion" placeholder bug |
| `MinimalUserSnapshot.full_name` | `backend/onyx/server/models.py`, `backend/onyx/server/manage/users.py` (`full_name=u.personal_name`) | No test — upstream dropped the field; we re-add it. Keep ours. |
| `auth_check` admin dependency | `backend/onyx/server/auth_check.py` (`current_admin_user` in accepted-dependency chain) | No test — dropping it breaks app startup for admin-only routes |
| Whitelabel branding | `WHITELABEL_NAME` in `backend/onyx/configs/app_configs.py`, `backend/onyx/server/settings/models.py`, `backend/onyx/server/settings/store.py`, `web/src/lib/settings/types.ts`, `web/src/lib/app/components.tsx` (logo), `web/src/app/app/components/WelcomeMessage.tsx` | grep `whitelabel_name`/`WHITELABEL_NAME` across those files |
| Google Drive write scopes + Calendar scope | `backend/onyx/connectors/google_utils/shared_constants.py`, `resources.py`, `google_kv.py`, `backend/ee/onyx/server/oauth/google_drive.py` | `pytest backend/tests/unit/onyx/connectors/google_drive/test_google_drive_scopes.py` |
| CRM frontend unit tests | `web/src/lib/crmService.test.ts`, `web/src/components/ContactAvatar.test.tsx`, `web/src/views/crm/crmOptions.test.ts`, `web/src/views/crm/components/crmDateUtils.test.ts`, `web/src/views/crm/components/CrmDateRangeFilter.test.ts` | `cd web && npx jest src/lib/crmService.test.ts src/components/ContactAvatar.test.tsx src/views/crm` |
| Cloudflare Tunnel  | `deployment/docker_compose/docker-compose.prod-tunnel.yml`, `deployment/docker_compose/env.ec2.cloudflare.template`, `deployment/data/nginx/app.conf.template.tunnel`, `deployment/docker_compose/onyx.service.tunnel`, `deployment/docker_compose/bootstrap-env.sh` | Files exist and are unmodified                                                                                                                                    |
| Image publishing + prod deploy | `.github/workflows/build-images.yml`, `deployment/docker_compose/docker-compose.prod.yml`, `deployment/docker_compose/env.prod.template`, `backend/Dockerfile` (no `--require-hashes`), `backend/Dockerfile.model_server` | Files exist; Dockerfile keeps hashless pip install (commit 03d16f7794) |
| Windows dev scripts | `scripts/run_api_server.ps1`, `run_bg_jobs.ps1`, `run_frontend.ps1`, `run_infra.ps1`, `run_model_server.ps1`, `stop_all.ps1`, `tail_logs.ps1`, `start_dev.ps1`, `start_bg_jobs.ps1`, `scripts/sync-verify.sh` | Files exist and are unmodified |
| CRM sidebar nav    | `web/src/sections/sidebar/AppSidebar.tsx`                                                                                               | CRM button present with SvgOrganization icon                                                                                                                      |
| Timezone in chat   | `web/src/app/app/services/lib.tsx` (payload field), `backend/onyx/chat/llm_loop.py` (`timezone` kwarg on `run_llm_loop`), `backend/onyx/utils/datetime_utils.py`, `backend/onyx/prompts/prompt_utils.py`, `backend/onyx/chat/prompt_utils.py` (calendar-tool timezone guidance) | `timezone` field in chat payload, `timezone` kwarg in `run_llm_loop`                                                                                              |
| LLM resiliency (Claude max_tokens + capacity backoff) | `backend/onyx/llm/multi_llm.py` (explicit `max_tokens` for Claude models, backoff retries on provider capacity errors), `backend/onyx/llm/model_capabilities.py`, `backend/onyx/llm/utils.py`, `backend/onyx/configs/model_configs.py`, `backend/onyx/configs/chat_configs.py`, `backend/onyx/chat/process_message.py` (user-facing capacity error text) | `pytest backend/tests/unit/onyx/llm/test_multi_llm.py backend/tests/unit/onyx/llm/test_multi_llm_stream_retry.py backend/tests/unit/onyx/llm/test_token_limit_lookups.py` — commits be0cc5db51, 6ea39ca4f0; `multi_llm.py` now conflicts every sync (recurring) |
| IMAP parsing + timeout fixes | `backend/onyx/connectors/imap/connector.py` (socket timeout, address-preserving header/body parsing), `backend/onyx/connectors/imap/models.py`, `backend/onyx/indexing/adapters/document_indexing_adapter.py` (no double commit in `post_index`) | `pytest backend/tests/unit/onyx/connectors/imap/test_imap_connector.py backend/tests/unit/onyx/indexing/test_email_trigger_emission.py` — commits 94988dace2, 8f9ec6e21c, 9c8eede6b3 |
| Chat fork ("Branch from here") | `backend/onyx/db/chat.py` (fork/copy helpers), `backend/onyx/db/models.py` (`ChatSession` fork-origin columns), `backend/onyx/server/query_and_chat/chat_backend.py` + `models.py` (fork route), migration `b3e1f7a2c9d4`, `web/src/hooks/useChatController.ts`, `web/src/app/app/stores/useChatSessionStore.ts`, `web/src/app/app/services/lib.tsx`, `web/src/sections/chat/ChatUI.tsx`, `ChatScrollContainer.tsx`, `web/src/views/AppPage.tsx`, `web/src/app/app/message/{HumanMessage,MultiModelPanel,MultiModelResponseView}.tsx`, `.../messageComponents/{AgentMessage,MessageToolbar}.tsx`, `web/src/sections/input/AppInputBar.tsx`, fork keys in all 9 `web/src/i18n/messages/*.json` | `pytest backend/tests/unit/onyx/db/test_chat_fork_files.py`; integration `backend/tests/integration/tests/chat/test_chat_fork.py`; e2e `web/tests/e2e/chat/chat_branch.spec.ts` — commit 2b1ac7b840 |

## Safety

- **`pre-sync-backup` branch** should always exist before starting a sync
- **Never force-push main** during a sync — if something goes wrong, reset to the backup branch
- **Check for secrets** before pushing — real AWS account IDs, KMS key IDs, API keys can slip into docs or configs
- **Don't commit `.claude/worktrees/`** — ensure `.gitignore` covers both root and `private_docs/` paths
