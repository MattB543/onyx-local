#!/usr/bin/env bash
#
# sync-verify.sh — runnable version of the "Verification Checklist (before pushing)"
# in docs/git-sync-playbook.md.
#
# Usage:
#   scripts/sync-verify.sh [--batch|--full]
#
#   --batch   cheap per-batch checks only:
#               conflict markers, npx tsc --noEmit, custom-feature pytest suites
#   --full    everything in the checklist (default):
#               commits behind upstream, tsc, next build, full unit tests, ruff,
#               prettier, alembic single head, secrets grep vs origin/main
#
# Every check prints PASS / FAIL / SKIP and the script keeps going after a
# failure. Exit code is non-zero if any check failed.
#
# Runs under Git Bash on Windows. Frontend commands run from web/, backend
# commands from backend/.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$REPO_ROOT/web"
BACKEND_DIR="$REPO_ROOT/backend"

MODE="full"
case "${1:---full}" in
  --batch) MODE="batch" ;;
  --full)  MODE="full" ;;
  -h|--help)
    grep '^#' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *)
    echo "Unknown argument: $1"
    echo "Usage: sync-verify.sh [--batch|--full]"
    exit 2
    ;;
esac

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
FAILED_CHECKS=()
SKIPPED_CHECKS=()

LOG_DIR="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/sync-verify.$$")"
mkdir -p "$LOG_DIR"

have() { command -v "$1" >/dev/null 2>&1; }

# Prefer the repo venv — bare `python` may be a broken pyenv shim (Git Bash on
# Windows resolves to the shim even when no pyenv version is set).
if [ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
  PYTHON="$REPO_ROOT/.venv/Scripts/python.exe"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="python"
fi
have_python() { "$PYTHON" --version >/dev/null 2>&1; }

# run_check <name> <function>
#   The function runs the check and returns:
#     0 = pass, 77 = skip (echo the reason first; 77 avoids colliding with tsc/pytest rc 2), anything else = fail.
#   All output is captured and only shown on failure.
run_check() {
  local name="$1"
  local fn="$2"
  local log="$LOG_DIR/$(echo "$name" | tr -c 'A-Za-z0-9' '_').log"

  "$fn" >"$log" 2>&1
  local rc=$?

  if [ "$rc" -eq 0 ]; then
    echo "PASS  $name"
    PASS_COUNT=$((PASS_COUNT + 1))
    # Surface NOTE: lines (e.g. playbook paths missing from the tree) even on pass.
    grep '^NOTE:' "$log" | sed 's/^/        /'
  elif [ "$rc" -eq 77 ]; then
    echo "SKIP  $name — $(tail -n 1 "$log")"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    SKIPPED_CHECKS+=("$name")
  else
    echo "FAIL  $name"
    sed 's/^/        | /' "$log" | tail -n 30
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED_CHECKS+=("$name")
  fi
}

# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

# Leftover conflict markers in tracked source files.
check_conflict_markers() {
  cd "$REPO_ROOT" || return 1
  local hits
  hits=$(git grep -n -- "<<<<<<< " -- '*.py' '*.ts' '*.tsx')
  if [ -n "$hits" ]; then
    echo "Conflict markers found in tracked files:"
    echo "$hits"
    return 1
  fi
  return 0
}

# git rev-list --count HEAD..upstream/main → 0
check_commits_behind() {
  cd "$REPO_ROOT" || return 1
  if ! git rev-parse --verify --quiet upstream/main >/dev/null; then
    echo "upstream/main not found (git fetch upstream)"
    return 77
  fi
  local behind
  behind=$(git rev-list --count HEAD..upstream/main)
  echo "commits behind upstream/main: $behind"
  [ "$behind" = "0" ]
}

# npx tsc --noEmit → 0 errors (or only upstream errors)
check_tsc() {
  if ! have npx; then echo "npx not available"; return 77; fi
  cd "$WEB_DIR" || return 1
  npx tsc --noEmit
}

# npx next build → compiles
check_next_build() {
  if ! have npx; then echo "npx not available"; return 77; fi
  cd "$WEB_DIR" || return 1
  npx next build
}

# "$PYTHON" -m pytest backend/tests/unit/ → all pass
check_unit_tests() {
  if ! have_python; then echo "python not available"; return 77; fi
  cd "$BACKEND_DIR" || return 1
  # os.geteuid does not exist on Windows; upstream test_log_collection.py calls it
  # at collection time and aborts the whole run — exclude it here (runs in CI).
  "$PYTHON" -m pytest tests/unit/ -q --ignore=tests/unit/ee/onyx/server/log_export/test_log_collection.py
}

# python -m ruff check backend/ → clean
# Must run from the repo root: the per-file-ignores in pyproject.toml are
# rooted there (backend/alembic/**, backend/tests/**, ...) and silently stop
# matching if ruff runs from inside backend/.
check_ruff() {
  if ! have_python; then echo "python not available"; return 77; fi
  cd "$REPO_ROOT" || return 1
  "$PYTHON" -m ruff check backend/
}

# Formatting: upstream moved web formatting from prettier to oxfmt (2026-07).
# oxfmt --check is only meaningful on LF checkouts — on Windows with
# core.autocrlf=true every file false-positives on line endings, so skip there.
check_prettier() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      echo "oxfmt --check needs an LF checkout; run in CI/Linux (autocrlf false-positives)"
      return 77
      ;;
  esac
  cd "$REPO_ROOT/web" || return 1
  bunx oxfmt --check src
}

check_prettier_old_unused() {
  if ! have npx; then echo "npx not available"; return 77; fi
  cd "$WEB_DIR" || return 1
  npx prettier --check "src/**"
}

# python -m alembic heads → single head
check_alembic_single_head() {
  if ! have_python; then echo "python not available"; return 77; fi
  cd "$BACKEND_DIR" || return 1
  local out heads
  out=$("$PYTHON" -m alembic heads 2>&1) || { echo "$out"; return 1; }
  echo "$out"
  heads=$(echo "$out" | grep -c "(head)")
  echo "head count: $heads"
  [ "$heads" = "1" ]
}

# git diff origin/main..HEAD | grep -iE "AKIA|aws_secret|password=" → no real secrets
check_secrets() {
  cd "$REPO_ROOT" || return 1
  if ! git rev-parse --verify --quiet origin/main >/dev/null; then
    echo "origin/main not found (git fetch origin)"
    return 77
  fi
  local hits
  hits=$(git diff origin/main..HEAD | grep -iE "AKIA|aws_secret|password=")
  if [ -n "$hits" ]; then
    echo "Potential secrets in diff vs origin/main (review each — some may be benign):"
    echo "$hits"
    return 1
  fi
  return 0
}

# Custom-feature pytest suites, from the "Custom Fork Features" table.
# Paths are repo-relative in the playbook; pytest runs from backend/.
run_feature_pytest() {
  if ! have_python; then echo "python not available"; return 77; fi
  cd "$BACKEND_DIR" || return 1

  local existing=()
  local missing=()
  local p
  for p in "$@"; do
    if [ -e "$p" ]; then
      existing+=("$p")
    else
      missing+=("$p")
    fi
  done

  if [ "${#missing[@]}" -gt 0 ]; then
    echo "NOTE: playbook path(s) not present in the tree: ${missing[*]}"
  fi

  if [ "${#existing[@]}" -eq 0 ]; then
    echo "no test paths from the playbook exist here: $*"
    return 77
  fi

  "$PYTHON" -m pytest "${existing[@]}" -q
}

check_pytest_crm() {
  run_feature_pytest \
    tests/unit/onyx/db/test_crm_queries.py \
    tests/unit/tools/test_crm_tool_packets.py \
    tests/unit/onyx/server/features/test_crm_api.py
}

check_pytest_kms() {
  run_feature_pytest \
    tests/unit/onyx/utils/test_kms_encryption.py \
    tests/unit/ee/onyx/utils/test_encryption.py \
    tests/unit/onyx/configs/test_secret_encryption_config.py
}

check_pytest_custom_jobs() {
  run_feature_pytest \
    tests/unit/onyx/custom_jobs/ \
    tests/unit/onyx/db/test_custom_jobs.py \
    tests/unit/onyx/server/manage/test_custom_jobs_api.py
}

check_pytest_calendar() {
  run_feature_pytest \
    tests/unit/tools/test_calendar_tool_packets.py \
    tests/unit/onyx/db/test_calendar_queries.py
}

check_pytest_email_triggers() {
  run_feature_pytest \
    tests/unit/onyx/indexing/test_email_trigger_emission.py
}

# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

echo "sync-verify.sh — mode: $MODE"
echo "repo: $REPO_ROOT"
echo

if [ "$MODE" = "batch" ]; then
  run_check "conflict markers"            check_conflict_markers
  run_check "tsc --noEmit"                check_tsc
  run_check "pytest: CRM module"          check_pytest_crm
  run_check "pytest: AWS KMS encryption"  check_pytest_kms
  run_check "pytest: custom jobs"         check_pytest_custom_jobs
  run_check "pytest: Google Calendar"     check_pytest_calendar
  run_check "pytest: email triggers"      check_pytest_email_triggers
else
  run_check "conflict markers"            check_conflict_markers
  run_check "commits behind upstream"     check_commits_behind
  run_check "tsc --noEmit"                check_tsc
  run_check "next build"                  check_next_build
  run_check "pytest: backend unit tests"  check_unit_tests
  run_check "pytest: CRM module"          check_pytest_crm
  run_check "pytest: AWS KMS encryption"  check_pytest_kms
  run_check "pytest: custom jobs"         check_pytest_custom_jobs
  run_check "pytest: Google Calendar"     check_pytest_calendar
  run_check "pytest: email triggers"      check_pytest_email_triggers
  run_check "ruff check"                  check_ruff
  run_check "oxfmt --check src (web fmt)"  check_prettier
  run_check "alembic single head"         check_alembic_single_head
  run_check "secrets in diff vs origin/main" check_secrets
fi

echo
echo "-------------------------------------------"
echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed, $SKIP_COUNT skipped"

if [ "$SKIP_COUNT" -gt 0 ]; then
  echo "Skipped:"
  for c in "${SKIPPED_CHECKS[@]}"; do echo "  - $c"; done
fi

if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "Failed:"
  for c in "${FAILED_CHECKS[@]}"; do echo "  - $c"; done
fi

if [ "$MODE" = "full" ]; then
  echo
  echo "Manual checklist item (not automatable):"
  echo "  [ ] Custom features functional: CRM, KMS, Calendar, custom jobs, deployment"
fi

echo "Logs: $LOG_DIR"

[ "$FAIL_COUNT" -eq 0 ]
