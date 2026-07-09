#!/usr/bin/env sh
set -eu

ENV_FILE="${ENV_FILE:-.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
else
  echo "No $ENV_FILE found. Copy .env.example to .env for local configuration."
fi

: "${CRYPTO_AGENT_SYMBOLS:=BTC/USDT,ETH/USDT,SOL/USDT}"
: "${SAFETY_DRY_RUN:=true}"
: "${KILL_SWITCH:=false}"
: "${TELEGRAM_ENABLED:=false}"
: "${ALLOW_LIVE_TRADING:=false}"
: "${DOCTOR_REQUIRE_TELEGRAM:=false}"
: "${DOCTOR_NETWORK:=false}"

failures=0

check_bool() {
  name="$1"
  value="${2:-}"
  case "$value" in
    true|false) ;;
    *)
      echo "Invalid boolean for $name: expected true or false, got '${value:-unset}'"
      failures=$((failures + 1))
      ;;
  esac
}

require_when_enabled() {
  flag_name="$1"
  flag_value="$2"
  required_name="$3"
  required_value="$4"
  if [ "$flag_value" = "true" ] && [ -z "$required_value" ]; then
    echo "$required_name is required when $flag_name=true"
    failures=$((failures + 1))
  fi
}

if command -v python3 >/dev/null 2>&1; then
  python3 --version
else
  echo "python3 is not installed or not on PATH"
  failures=$((failures + 1))
fi

if [ -x ".venv/bin/python" ]; then
  DOCTOR_PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  DOCTOR_PY="python3"
else
  DOCTOR_PY=""
fi

if [ -n "$DOCTOR_PY" ] && [ -f crypto_agent/main.py ]; then
  if ! "$DOCTOR_PY" -c "import uvicorn" >/dev/null 2>&1; then
    echo "uvicorn is not installed for $DOCTOR_PY; run make bootstrap before make run"
  fi
fi

mkdir -p "${DATA_DIR:-./data}" "${LOG_DIR:-./logs}"

check_bool SAFETY_DRY_RUN "$SAFETY_DRY_RUN"
check_bool KILL_SWITCH "$KILL_SWITCH"
check_bool TELEGRAM_ENABLED "$TELEGRAM_ENABLED"
check_bool ALLOW_LIVE_TRADING "$ALLOW_LIVE_TRADING"
check_bool DOCTOR_REQUIRE_TELEGRAM "$DOCTOR_REQUIRE_TELEGRAM"
check_bool DOCTOR_NETWORK "$DOCTOR_NETWORK"

if [ "$ALLOW_LIVE_TRADING" = "true" ] && [ "$SAFETY_DRY_RUN" = "true" ]; then
  echo "ALLOW_LIVE_TRADING=true conflicts with SAFETY_DRY_RUN=true"
  failures=$((failures + 1))
fi

if [ "$KILL_SWITCH" = "true" ]; then
  echo "Kill switch is enabled; startup should remain blocked by the application."
fi

require_when_enabled TELEGRAM_ENABLED "$TELEGRAM_ENABLED" TELEGRAM_BOT_TOKEN "${TELEGRAM_BOT_TOKEN:-}"
require_when_enabled TELEGRAM_ENABLED "$TELEGRAM_ENABLED" TELEGRAM_CHAT_ID "${TELEGRAM_CHAT_ID:-}"
require_when_enabled DOCTOR_REQUIRE_TELEGRAM "$DOCTOR_REQUIRE_TELEGRAM" TELEGRAM_BOT_TOKEN "${TELEGRAM_BOT_TOKEN:-}"
require_when_enabled DOCTOR_REQUIRE_TELEGRAM "$DOCTOR_REQUIRE_TELEGRAM" TELEGRAM_CHAT_ID "${TELEGRAM_CHAT_ID:-}"

if [ -z "$CRYPTO_AGENT_SYMBOLS" ]; then
  echo "CRYPTO_AGENT_SYMBOLS must include at least one symbol"
  failures=$((failures + 1))
fi

if [ "$DOCTOR_NETWORK" = "true" ]; then
  echo "Network diagnostics are intentionally not run by default. Add provider-specific checks here when endpoints are finalized."
fi

if [ "$failures" -gt 0 ]; then
  echo "Doctor found $failures issue(s)"
  exit 1
fi

echo "Doctor checks passed"
