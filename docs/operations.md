# Operations

## Local Runbook

1. Bootstrap:

   ```sh
   make bootstrap
   ```

2. Edit `.env` and keep `SAFETY_DRY_RUN=true`.

3. Validate:

   ```sh
   make doctor
   ```

4. Start:

   ```sh
   make run
   ```

By default the runner serves `crypto_agent.main:app` with uvicorn. Set `CRYPTO_AGENT_CMD` only when you want to override startup.

For live websocket monitoring instead of the API service:

```sh
CRYPTO_AGENT_CMD="python3 -m crypto_agent.runner"
```

## Docker Runbook

```sh
make docker-build
make up
make logs
make down
```

The Compose stack runs:

- `crypto-agent`: FastAPI service on `${HOST_PORT:-8000}`
- `postgres`: local Postgres for `DATABASE_URL`
- `redis`: local Redis for `REDIS_URL`

The app service mounts:

- `./data` to `/app/data`
- `./logs` to `/app/logs`

## Health Checks

The app exposes `/health`, so the default local check is:

```sh
CRYPTO_AGENT_HEALTHCHECK_URL=http://127.0.0.1:8000/health
```

Use this form if you change `APP_PORT` to `8080`:

```sh
CRYPTO_AGENT_HEALTHCHECK_URL=http://127.0.0.1:8080/health
```

For worker-only deployments, use:

```sh
CRYPTO_AGENT_HEALTHCHECK_CMD="python -m crypto_agent.healthcheck"
```

Without either value, `scripts/healthcheck.sh` reports healthy unless `KILL_SWITCH=true`. This avoids marking worker-only deployments unhealthy before a probe exists.

## Telegram Smoke Test

Before sending production-like alerts:

1. Set `TELEGRAM_ENABLED=true`.
2. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Keep `SAFETY_DRY_RUN=true`.
4. Run a small local signal loop or application-provided notifier test.
5. Confirm messages include symbol, direction, confidence, timeframe, timestamp, and risk notes.

## Operational Safety

- Do not run unattended with `ALLOW_LIVE_TRADING=true`.
- Keep exchange keys read-only for alerting phases.
- Treat `.env` as secret material.
- Rotate any key that appears in chat, logs, screenshots, or commits.
- Enable `KILL_SWITCH=true` to prevent startup during incidents.
- Prefer paper mode until signals have backtest and forward-test evidence.

## Incident Checklist

1. Set `KILL_SWITCH=true`.
2. Stop the worker with `make down` or terminate the local process.
3. Preserve `logs/` and relevant `data/` files.
4. Rotate affected API or Telegram keys.
5. Review audit records for sent, blocked, and repeated signals.
6. Restart only after `make doctor` passes and the root cause is understood.
