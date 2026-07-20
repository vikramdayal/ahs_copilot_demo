#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly APP_ROOT="/app"
readonly DATA_MODE="${AHS_DATA_MODE:-sample}"
readonly CONFIG_PATH="${AHS_CONFIG_PATH:-/app/config/ahs_engine.toml}"
readonly APP_PORT="${PORT:-8501}"

fail() {
  printf 'AHS startup failed: %s\n' "$1" >&2
  exit 2
}

load_secret_file() {
  local variable_name="$1"
  local file_variable_name="${variable_name}_FILE"
  local direct_value="${!variable_name:-}"
  local file_path="${!file_variable_name:-}"

  if [[ -n "$direct_value" && -n "$file_path" ]]; then
    fail "Both ${variable_name} and ${file_variable_name} are set; choose one credential source."
  fi

  if [[ -n "$file_path" ]]; then
    [[ -r "$file_path" ]] || fail "Secret file for ${variable_name} is not readable."
    local secret_value
    secret_value="$(<"$file_path")"
    [[ -n "$secret_value" ]] || fail "Secret file for ${variable_name} is empty."
    printf -v "$variable_name" '%s' "$secret_value"
    export "$variable_name"
    unset "$file_variable_name"
  fi
}

for secret_name in \
  OPENAI_API_KEY \
  ANTHROPIC_API_KEY \
  AWS_ACCESS_KEY_ID \
  AWS_SECRET_ACCESS_KEY \
  AWS_SESSION_TOKEN
do
  load_secret_file "$secret_name"
done

case "$APP_PORT" in
  ''|*[!0-9]*) fail "PORT must be an integer from 1 through 65535." ;;
esac
if (( APP_PORT < 1 || APP_PORT > 65535 )); then
  fail "PORT must be an integer from 1 through 65535."
fi

case "$DATA_MODE" in
  sample|production) ;;
  *) fail "Unsupported AHS_DATA_MODE=${DATA_MODE}; expected sample or production." ;;
esac

mkdir -p /tmp/ahs-fixtures /tmp/ahs-duckdb "$HOME"
[[ -r "$CONFIG_PATH" ]] || fail "AHS engine configuration is not readable: ${CONFIG_PATH}"

python "$APP_ROOT/scripts/preflight.py" \
  --config "$CONFIG_PATH" \
  --data-mode "$DATA_MODE"

exec python -m streamlit run "$APP_ROOT/src/ahs_copilot/ui/streamlit_app.py" \
  --server.address=0.0.0.0 \
  --server.port="$APP_PORT" \
  --server.headless=true \
  --server.runOnSave=false \
  --server.fileWatcherType=none \
  --server.enableXsrfProtection=true \
  --server.enableCORS=true \
  --browser.gatherUsageStats=false
