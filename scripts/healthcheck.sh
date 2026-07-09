#!/usr/bin/env sh
set -eu

if [ -n "${CRYPTO_AGENT_HEALTHCHECK_CMD:-}" ]; then
  sh -c "$CRYPTO_AGENT_HEALTHCHECK_CMD"
  exit $?
fi

if [ -n "${CRYPTO_AGENT_HEALTHCHECK_URL:-}" ]; then
  curl -fsS --max-time 5 "$CRYPTO_AGENT_HEALTHCHECK_URL" >/dev/null
  exit $?
fi

if [ "${KILL_SWITCH:-false}" = "true" ]; then
  echo "Kill switch enabled"
  exit 1
fi

echo "No explicit health check configured; treating worker container as healthy"
exit 0
