#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/env.config"
ENV_FILE="${SCRIPT_DIR}/.env"
DEFAULT_REGION="us-east-2"
DEFAULT_SSM_PREFIX="/onyx/prod/secrets"
SSM_PAGE_SIZE=10

log() {
    echo "[$(date -Iseconds)] [bootstrap] $*"
}

get_config_value() {
    local key="$1"
    if [[ ! -f "$CONFIG_FILE" ]]; then
        return 0
    fi

    local line
    line="$(grep -E "^${key}=" "$CONFIG_FILE" | tail -n 1 || true)"
    if [[ -z "$line" ]]; then
        return 0
    fi

    printf '%s' "${line#*=}"
}

if [[ ! -f "$CONFIG_FILE" ]]; then
    log "ERROR: Config template not found at $CONFIG_FILE"
    exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
    log "ERROR: AWS CLI is not installed or not in PATH"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    log "ERROR: jq is not installed or not in PATH"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    log "ERROR: python3 is not installed or not in PATH"
    exit 1
fi

REGION="${AWS_REGION_NAME:-$(get_config_value AWS_REGION_NAME)}"
REGION="${REGION:-$DEFAULT_REGION}"

SSM_PREFIX="${AWS_SSM_SECRETS_PREFIX:-$(get_config_value AWS_SSM_SECRETS_PREFIX)}"
SSM_PREFIX="${SSM_PREFIX:-$DEFAULT_SSM_PREFIX}"

log "Using AWS region: ${REGION}"
log "Fetching secrets from SSM path: ${SSM_PREFIX}"

umask 077
TMPFILE="$(mktemp "${ENV_FILE}.XXXXXX")"
PARAMS_FILE="$(mktemp "${ENV_FILE}.params.XXXXXX")"
ERROR_FILE="$(mktemp "${ENV_FILE}.stderr.XXXXXX")"
trap 'rm -f "$TMPFILE" "$PARAMS_FILE" "$ERROR_FILE"' EXIT

: > "$PARAMS_FILE"

NEXT_TOKEN=""
PAGE_COUNT=0
PARAM_COUNT=0

while true; do
    PAGE_COUNT=$((PAGE_COUNT + 1))

    AWS_ARGS=(
        ssm get-parameters-by-path
        --path "${SSM_PREFIX}"
        --with-decryption
        --recursive
        --region "${REGION}"
        --output json
        --page-size "${SSM_PAGE_SIZE}"
        --max-items "${SSM_PAGE_SIZE}"
    )

    if [[ -n "$NEXT_TOKEN" ]]; then
        AWS_ARGS+=(--starting-token "$NEXT_TOKEN")
    fi

    : > "$ERROR_FILE"
    if ! SSM_RESPONSE="$(aws "${AWS_ARGS[@]}" 2>"$ERROR_FILE")"; then
        log "ERROR: Failed to fetch SSM parameters: $(<"$ERROR_FILE")"
        exit 1
    fi

    PAGE_PARAM_COUNT="$(printf '%s' "$SSM_RESPONSE" | jq '(.Parameters // []) | length')"
    PARAM_COUNT=$((PARAM_COUNT + PAGE_PARAM_COUNT))
    printf '%s' "$SSM_RESPONSE" | jq -c '(.Parameters // [])[]?' >> "$PARAMS_FILE"

    NEXT_TOKEN="$(printf '%s' "$SSM_RESPONSE" | jq -r '.NextToken // empty')"
    if [[ -z "$NEXT_TOKEN" ]]; then
        break
    fi
done

log "Fetched ${PARAM_COUNT} secret(s) from SSM across ${PAGE_COUNT} page(s)."

if [[ "$PARAM_COUNT" -eq 0 ]]; then
    log "WARNING: No secrets found under ${SSM_PREFIX}. Continuing with config-only .env."
fi

python3 - "$CONFIG_FILE" "$PARAMS_FILE" "$TMPFILE" "$(date -Iseconds)" <<'PY'
import json
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
params_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
fetched_at = sys.argv[4]

env_key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
env_assignment_pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def serialize_compose_env(value: str) -> str:
    # Docker Compose's dotenv parser accepts JSON-style double-quoted escapes.
    # Doubling "$" preserves literal dollars instead of triggering interpolation.
    return json.dumps(value, ensure_ascii=False).replace("$", "$$")


secrets: dict[str, str] = {}
source_names: dict[str, str] = {}
with params_path.open("r", encoding="utf-8") as handle:
    for raw_line in handle:
        line = raw_line.strip()
        if not line:
            continue

        parameter = json.loads(line)
        parameter_name = parameter["Name"].rstrip("/")
        secret_key = parameter_name.split("/")[-1]

        if not env_key_pattern.fullmatch(secret_key):
            fail(
                f"Invalid SSM parameter name '{parameter['Name']}'. "
                "The final path segment must be a valid environment variable key."
            )

        existing_name = source_names.get(secret_key)
        if existing_name and existing_name != parameter["Name"]:
            fail(
                "Duplicate SSM parameter keys detected after path-to-env conversion: "
                f"'{existing_name}' and '{parameter['Name']}' both map to '{secret_key}'."
            )

        source_names[secret_key] = parameter["Name"]
        secrets[secret_key] = parameter.get("Value", "")


output_lines: list[str] = []
with config_path.open("r", encoding="utf-8") as handle:
    for raw_line in handle.read().splitlines():
        match = env_assignment_pattern.match(raw_line)
        if match and match.group(1) in secrets:
            continue
        output_lines.append(raw_line)

if secrets:
    if output_lines and output_lines[-1] != "":
        output_lines.append("")
    output_lines.append(f"# --- Secrets from SSM (fetched at {fetched_at}) ---")
    for secret_key in sorted(secrets):
        output_lines.append(f"{secret_key}={serialize_compose_env(secrets[secret_key])}")

with output_path.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write("\n".join(output_lines) + "\n")
PY

mv "$TMPFILE" "$ENV_FILE"
rm -f "$PARAMS_FILE" "$ERROR_FILE"
trap - EXIT

log ".env written successfully with ${PARAM_COUNT} secret(s) + config values."
