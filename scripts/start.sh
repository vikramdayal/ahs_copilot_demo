#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly APP_ROOT="/app"
readonly DATA_MODE="${AHS_DATA_MODE:-sample}"
readonly CONFIG_PATH="${AHS_CONFIG_PATH:-/app/config/ahs_engine.toml}"
readonly APP_PORT="${PORT:-8501}"

load_secret_file() {
  local variable_name="$1"
  local file_variable_name="${variable_name}_FILE"
  local direct_value="${!variable_name:-}"
  local file_path="${!file_variable_name:-}"

  if [[ -n "$direct_value" && -n "$file_path" ]]; then
    echo "Both ${variable_name} and ${file_variable_name} are set; choose one credential source." >&2
    exit 2
  fi

  if [[ -n "$file_path" ]]; then
    if [[ ! -r "$file_path" ]]; then
      echo "Secret file for ${variable_name} is not readable: ${file_path}" >&2
      exit 2
    fi
    printf -v "$variable_name" '%s' "$(<"$file_path")"
    export "$variable_name"
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

case "$DATA_MODE" in
  sample)
    mkdir -p /tmp/ahs-fixtures /tmp/ahs-duckdb "$HOME"
    if [[ -d "$APP_ROOT/tests/fixtures/synthetic" ]]; then
      cp -a "$APP_ROOT/tests/fixtures/synthetic/." /tmp/ahs-fixtures/
    fi
    ;;
  production)
    mkdir -p /tmp/ahs-duckdb "$HOME"
    ;;
  *)
    echo "Unsupported AHS_DATA_MODE=${DATA_MODE}; expected sample or production." >&2
    exit 2
    ;;
esac

if [[ ! -r "$CONFIG_PATH" ]]; then
  echo "AHS engine configuration is not readable: ${CONFIG_PATH}" >&2
  exit 2
fi

python "$APP_ROOT/scripts/preflight.py" \
  --config "$CONFIG_PATH" \
  --data-mode "$DATA_MODE"

exec python -m streamlit run "$APP_ROOT/src/ahs_copilot/ui/app.py" \
  --server.address=0.0.0.0 \
  --server.port="$APP_PORT" \
  --server.headless=true \
  --server.fileWatcherType=none \
  --browser.gatherUsageStats=false
