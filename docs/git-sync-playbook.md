# Playbook: Batched Upstream Sync for onyx-local Fork

## Overview

This playbook documents how to sync MattB543/onyx-local with onyx-dot-app/onyx when 100+ commits have accumulated. It was developed and refined during a 438-commit sync across 9 batches (completed March 2026).

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

Keep this as a runnable script (`scripts/sync-verify.sh`) so agents and the Codex checker can execute it mechanically — per batch for the cheap checks (tsc, custom-feature pytest), and in full before pushing.

Known baseline (as of 2026-07-29, ruff-clean tree):

- `ruff check backend/` must run from the **repo root** — the per-file-ignores in `pyproject.toml` are rooted there and silently stop matching if run from inside `backend/`. The script does this correctly.
- Fork code is ruff-clean; a nonzero ruff result after a sync means the merge introduced it.
- On the Windows dev box, ~27 unit tests fail for environmental reasons (PDF fixtures, Docker-dependent sandbox_proxy tests, metrics timing) — in `test_pdf.py`, `test_simple_job_terminate.py`, `test_save_chat.py`, `test_confluence_checkpointing.py`, `sandbox_proxy/`, `server/metrics/`. Failures **outside** that set are real regressions.

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
- **Upstream file moves confuse git** — files moved from `refresh-components/` to `sections/` or `assistants/` to `agents/` cause rename-tracking conflicts. Take theirs.
- **EE endpoint hardening** — after sync, `fetchEnterpriseSettingsSS` and `fetchCustomAnalyticsScriptSS` may need `response.ok` guards and 404 tolerance for non-enterprise deployments
- **`LICENSE_ENFORCEMENT_ENABLED=false`** should be set in dev scripts to match backend behavior

### Timing

The full 438-commit sync took ~3 sessions across 2 days:

- Batches 1-6: first session (analysis + implementation per batch, ~45 min each)
- Batches 7-9: second session (~30 min each, patterns were established)
- Post-sync fixes: ~2 hours (type drift, test failures, alembic, formatting)

## Custom Fork Features (must preserve in every sync)

Refresh this table before each sync (Pre-work step 4) — diff `upstream/main..HEAD` and reconcile against it.

| Feature            | Key files                                                                                                                               | How to verify                                                                                                                                                     |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CRM module         | `backend/onyx/db/crm.py`, `backend/onyx/tools/crm/`, `web/src/refresh-pages/crm/`, `web/src/refresh-pages/Crm*.tsx`                     | `pytest backend/tests/unit/onyx/db/test_crm_queries.py backend/tests/unit/tools/test_crm_tool_packets.py backend/tests/unit/onyx/server/features/test_crm_api.py` |
| AWS KMS encryption | `backend/onyx/utils/encryption.py`, `backend/ee/onyx/utils/encryption.py`                                                               | `pytest backend/tests/unit/onyx/utils/test_kms_encryption.py backend/tests/unit/ee/onyx/utils/test_encryption.py backend/tests/unit/onyx/configs/test_secret_encryption_config.py` |
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
