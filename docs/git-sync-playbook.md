# Playbook: Batched Upstream Sync for onyx-local Fork

## Overview

This playbook documents how to sync MattB543/onyx-local with onyx-dot-app/onyx when 100+ commits have accumulated. It was developed and refined during a 438-commit sync across 9 batches (completed March 2026).

The approach: merge upstream in batches of ~50 commits using a 3-stage Opus agent pipeline per batch, with human decision-making between analysis and implementation.

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

### 4. Plan batch boundaries

- **~50 commits per batch** is the sweet spot (enough context for the agent, manageable conflict count)
- **Align boundaries with major PRs** — don't split a large refactor across batches
- **Isolate high-risk changes** — give major reworks (e.g., LLM provider refactor, component library migration) their own batch
- Scan upstream PRs in the range to identify risky ones:
  ```bash
  MERGE_BASE=$(git merge-base HEAD upstream/main)
  git log --oneline ${MERGE_BASE}..upstream/main | head -50  # first batch preview
  ```

## Per-Batch Workflow: 3-Stage Agent Pipeline

### Computing the target commit

```bash
MERGE_BASE=$(git merge-base HEAD upstream/main)
REMAINING=$(git rev-list --reverse ${MERGE_BASE}..upstream/main | wc -l)
TARGET=$(git rev-list --reverse ${MERGE_BASE}..upstream/main | sed -n '50p')  # 50th remaining
git log --oneline $TARGET -1  # verify
```

After each batch merges, `MERGE_BASE` advances automatically — always recompute.

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

1. Runs `git merge <target> --no-edit` in the worktree
2. Resolves manual blend conflicts first (reads files, applies precise edits)
3. Bulk-resolves "take theirs" files: `git checkout --theirs <file>`
4. Handles modify/delete conflicts: `git rm <file>` for accepted deletions
5. Stages everything: `git add -A`
6. Verifies no conflict markers: `grep -r "<<<<<<< " --include="*.py" --include="*.ts" --include="*.tsx" .`
7. Commits: `git commit --no-edit`

### Merging Worktree Back to Main

After the implementation agent completes:

```bash
git merge <worktree-branch> --no-edit
```

**This will always produce overlap conflicts** because the worktree branched from main before the batch merge. Resolution is simple — take the worktree's version for ALL overlap conflicts:

```bash
# Get list of conflicted files
CONFLICTS=$(git diff --name-only --diff-filter=U)
# Take worktree's version for each
echo "$CONFLICTS" | while read f; do git checkout <worktree-branch> -- "$f"; done
# Commit
git add -A && git commit --no-edit --no-verify
```

**Important:** Use `--no-verify` on the merge commit if pre-commit hooks are slow — they can hang on large merges. The code was already verified in the worktree.

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
| `web/src/hooks/useAppFocus.ts`                          | `"crm"` in AppFocusType union   | **KEEP OURS.** Our version is a superset — has `"crm"` plus all upstream types. Just add any new upstream types to our union.                                         |
| `web/src/app/app/services/lib.tsx`                      | `timezone` in chat payload      | **MANUAL BLEND.** Keep both `timezone` (ours) and `additional_context` (theirs) in the payload. Import conflict: take theirs.                                         |
| `web/src/refresh-components/inputs/InputComboBox/`      | `onClear` prop                  | **MANUAL BLEND.** Keep both `onClear` (ours) and `showOtherOptions` (theirs) in both `InputComboBox.tsx` and `types.ts`.                                              |

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
- **Type changes:** `MinimalUserSnapshot.full_name` removed (use `.email`), enum members dropped/renamed
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

- **50-commit batches** were the right size — enough context for meaningful merge, manageable conflict count (4-65 per batch)
- **Isolated worktrees** for implementation agents — safe to attempt merges without affecting main
- **Collapsing stages 2+3** for simple batches saved significant time
- **Consistent conflict resolution patterns** — the same ~8 files conflict every batch with the same resolution, making later batches faster
- **`--no-verify` on merge commits** — pre-commit hooks can hang on large merges; verification was done in the worktree

### What to watch out for

- **Worktree overlap conflicts are expected** — always take the worktree's version, never try to re-resolve
- **`.claude/worktrees/` directories** get accidentally staged by `git add -A` — ensure `.gitignore` covers them
- **Modify/delete conflicts recur** for files upstream deleted — accept deletion and `git rm` each time until they stop appearing
- **Upstream file moves confuse git** — files moved from `refresh-components/` to `sections/` or `assistants/` to `agents/` cause rename-tracking conflicts. Take theirs.
- **EE endpoint hardening** — after sync, `fetchEnterpriseSettingsSS` and `fetchCustomAnalyticsScriptSS` may need `response.ok` guards and 404 tolerance for non-enterprise deployments
- **`LICENSE_ENFORCEMENT_ENABLED=false`** should be set in dev scripts to match backend behavior

### Timing

The full 438-commit sync took ~3 sessions across 2 days:

- Batches 1-6: first session (analysis + implementation per batch, ~45 min each)
- Batches 7-9: second session (~30 min each, patterns were established)
- Post-sync fixes: ~2 hours (type drift, test failures, alembic, formatting)

## Custom Fork Features (must preserve in every sync) - this needs to be checked and update before each sync. Check all custom fork features / files / commits to understand what we need to keep and merge.

| Feature            | Key files                                                                                                                               | How to verify                                                                                                                                                     |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CRM module         | `backend/onyx/db/crm.py`, `backend/onyx/tools/crm/`, `web/src/refresh-pages/crm/`, `web/src/refresh-pages/Crm*.tsx`                     | `pytest backend/tests/unit/onyx/db/test_crm_queries.py backend/tests/unit/tools/test_crm_tool_packets.py backend/tests/unit/onyx/server/features/test_crm_api.py` |
| AWS KMS encryption | `backend/onyx/utils/encryption.py`, `backend/ee/onyx/utils/encryption.py`                                                               | `pytest backend/tests/unit/onyx/utils/test_encryption.py backend/tests/unit/onyx/configs/test_secret_encryption_config.py`                                        |
| Custom jobs        | `backend/onyx/custom_jobs/`, `backend/onyx/server/manage/custom_jobs/`                                                                  | `pytest backend/tests/unit/onyx/custom_jobs/ backend/tests/unit/onyx/db/test_custom_jobs.py backend/tests/unit/onyx/server/manage/test_custom_jobs_api.py`        |
| Google Calendar    | `web/src/lib/types.ts` (ValidSources.GoogleCalendar), `web/src/lib/connectors/connectors.tsx`, `web/src/lib/sources.ts`, callback route | `pytest backend/tests/unit/tools/test_calendar_tool_packets.py backend/tests/unit/onyx/db/test_calendar_queries.py`                                               |
| Email triggers     | `backend/onyx/indexing/adapters/document_indexing_adapter.py`                                                                           | `pytest backend/tests/unit/onyx/indexing/test_email_trigger_emission.py`                                                                                          |
| Cloudflare Tunnel  | `deployment/docker_compose/docker-compose.prod-tunnel.yml`, `deployment/docker_compose/env.ec2.cloudflare.template`                     | Files exist and are unmodified                                                                                                                                    |
| CRM sidebar nav    | `web/src/sections/sidebar/AppSidebar.tsx`                                                                                               | CRM button present with SvgOrganization icon                                                                                                                      |
| Timezone in chat   | `web/src/app/app/services/lib.tsx`, `backend/onyx/chat/process_message.py`                                                              | `timezone` field in chat payload, `timezone` kwarg in `run_llm_loop`                                                                                              |

## Safety

- **`pre-sync-backup` branch** should always exist before starting a sync
- **Never force-push main** during a sync — if something goes wrong, reset to the backup branch
- **Check for secrets** before pushing — real AWS account IDs, KMS key IDs, API keys can slip into docs or configs
- **Don't commit `.claude/worktrees/`** — ensure `.gitignore` covers both root and `private_docs/` paths
