#!/usr/bin/env sh
set -eu

ENV_FILE="${ENV_FILE:-.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

mkdir -p "${DATA_DIR:-./data}" "${LOG_DIR:-./logs}"

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "No Python interpreter found. Install Python 3 or run make bootstrap."
  exit 1
fi

if [ -d src ]; then
  export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
fi

if [ "${KILL_SWITCH:-false}" = "true" ]; then
  echo "KILL_SWITCH=true; refusing to start"
  exit 1
fi

if [ -n "${CRYPTO_AGENT_CMD:-}" ]; then
  echo "Starting crypto agent with CRYPTO_AGENT_CMD"
  exec sh -c "$CRYPTO_AGENT_CMD"
fi

run_uvicorn() {
  app_ref="$1"
  host="${APP_HOST:-0.0.0.0}"
  port="${APP_PORT:-8000}"
  if ! "$PYTHON_BIN" -c "import uvicorn" >/dev/null 2>&1; then
    echo "uvicorn is not installed for $PYTHON_BIN. Run make bootstrap or set CRYPTO_AGENT_CMD to a command that exists."
    exit 1
  fi
  exec "$PYTHON_BIN" -m uvicorn "$app_ref" --host "$host" --port "$port"
}

if [ -f crypto_agent/cli.py ] || [ -f src/crypto_agent/cli.py ]; then
  exec "$PYTHON_BIN" -m crypto_agent.cli
fi

if [ -f crypto_agent/main.py ] || [ -f src/crypto_agent/main.py ]; then
  if grep -q "FastAPI" crypto_agent/main.py 2>/dev/null || grep -q "FastAPI" src/crypto_agent/main.py 2>/dev/null; then
    run_uvicorn "crypto_agent.main:app"
  fi
  exec "$PYTHON_BIN" -m crypto_agent.main
fi

if [ -f crypto_agent/app.py ] || [ -f src/crypto_agent/app.py ]; then
  exec "$PYTHON_BIN" -m crypto_agent.app
fi

if [ -f crypto_agent/__main__.py ] || [ -f src/crypto_agent/__main__.py ]; then
  exec "$PYTHON_BIN" -m crypto_agent
fi

if [ -f main.py ]; then
  exec "$PYTHON_BIN" main.py
fi

cat >&2 <<'MSG'
No application entry point was found.

Set CRYPTO_AGENT_CMD in .env, for example:
  CRYPTO_AGENT_CMD="python -m crypto_agent.main"

The deployment surface is ready, but the Python application entry point still needs to be supplied.
MSG
exit 1
