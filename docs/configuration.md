# Configuration

Copy `.env.example` to `.env` before running locally:

```sh
cp .env.example .env
```

## Application Runtime

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | Environment label returned by `/health` and used in settings. |
| `LOG_LEVEL` | `INFO` | Logging verbosity. |
| `APP_HOST` | `0.0.0.0` | Host used by the local uvicorn runner. |
| `APP_PORT` | `8000` | Container and local port used by uvicorn. |
| `HOST_PORT` | `8000` | Host port published by Docker Compose. |
| `CRYPTO_AGENT_CMD` | empty | Explicit command used by `scripts/run-local.sh`. |
| `CRYPTO_AGENT_MODE` | `paper` | Runtime mode. Keep `paper` for MVP alerting. |
| `CRYPTO_AGENT_TIMEZONE` | `UTC` | Timezone for reports and scheduled windows. |

## Market Data

| Variable | Default | Purpose |
| --- | --- | --- |
| `QUOTE_ASSET` | `USDT` | Quote asset for top-market discovery. |
| `TOP_ASSET_LIMIT` | `5` | Number of top non-stablecoin assets to consider. |
| `SIGNAL_INTERVAL_SECONDS` | `60` | Signal loop cadence for app code. |
| `SIGNAL_COOLDOWN_SECONDS` | `900` | Cooldown window between repeated signals. |
| `MINIMUM_CONFIDENCE` | `0.62` | Current app-level confidence threshold. |
| `BACKFILL_CANDLES` | `200` | Historical candles fetched per symbol/timeframe at runner startup so indicators are warm from the first live candle. |
| `STOP_ATR_MULTIPLIER` | `1.5` | Stop distance in ATR multiples. Tuned value from the walk-forward optimizer: `2.0`. |
| `TARGET_R_MULTIPLE` | `1.5` | First take-profit as a multiple of the stop distance. Tuned value: `0.5` (tight target, high hit rate). |
| `REGIME_FILTER` | empty | Restrict BUY/SELL alerts to `trending` or `ranging` regimes; empty allows any. |
| `CRYPTO_AGENT_SYMBOLS` | `BTC/USDT,ETH/USDT,SOL/USDT` | Comma-separated market universe. |
| `CRYPTO_AGENT_TIMEFRAME` | `5m` | Candle interval for the default signal loop. |
| `CRYPTO_AGENT_POLL_INTERVAL_SECONDS` | `60` | Worker poll cadence. |
| `EXCHANGE_PROVIDER` | `binance` | Preferred provider identifier. |
| `COINGECKO_BASE_URL` | `https://api.coingecko.com/api/v3` | CoinGecko REST API base URL. |
| `BINANCE_STREAM_BASE_URL` | `wss://stream.binance.com:9443/stream` | Binance websocket stream base URL. |

## Safety

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAFETY_DRY_RUN` | `true` | Prevents live execution behavior. |
| `KILL_SWITCH` | `false` | Blocks startup or health when enabled. |
| `SIGNAL_MIN_CONFIDENCE` | `0.70` | Minimum score required before notifying. |
| `MAX_SIGNALS_PER_HOUR` | `6` | Alert rate limit. |
| `MAX_POSITION_RISK_PCT` | `1.0` | Per-signal risk cap for sizing logic. |
| `MAX_DAILY_LOSS_PCT` | `3.0` | Daily risk cap for future execution phases. |
| `ALLOW_LIVE_TRADING` | `false` | Must stay false until an explicit safety review. |

## Telegram

| Variable | Default | Purpose |
| --- | --- | --- |
| `TELEGRAM_ENABLED` | `false` | Enables Telegram notifications. |
| `TELEGRAM_BOT_TOKEN` | empty | Bot token from BotFather. |
| `TELEGRAM_CHAT_ID` | empty | Destination chat or channel id. |
| `TELEGRAM_PARSE_MODE` | `Markdown` | Formatting mode for messages. |

## Provider Keys

| Variable | Purpose |
| --- | --- |
| `BINANCE_API_KEY` | Binance API key. Use read-only permissions for MVP. |
| `BINANCE_API_SECRET` | Binance API secret. |
| `COINBASE_API_KEY` | Coinbase API key. Use read-only permissions for MVP. |
| `COINBASE_API_SECRET` | Coinbase API secret. |
| `COINGECKO_API_KEY` | CoinGecko API key. |

## Storage and Health

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATA_DIR` | `./data` | Runtime state directory. |
| `LOG_DIR` | `./logs` | Local log directory. |
| `SQLITE_PATH` | `./data/crypto_agent.sqlite3` | Default local database path. |
| `DATABASE_URL` | Postgres Compose URL | Async database URL for service persistence. |
| `REDIS_URL` | Redis Compose URL | Redis URL for queues, caches, or rate limits. |
| `POSTGRES_DB` | `crypto_agent` | Compose Postgres database name. |
| `POSTGRES_USER` | `crypto` | Compose Postgres user. |
| `POSTGRES_PASSWORD` | `crypto` | Compose Postgres password. Replace outside local dev. |
| `CRYPTO_AGENT_HEALTHCHECK_URL` | `http://127.0.0.1:8000/health` | Optional HTTP health endpoint. |
| `CRYPTO_AGENT_HEALTHCHECK_CMD` | empty | Optional shell command health check. |
| `DOCTOR_REQUIRE_TELEGRAM` | `false` | Makes `scripts/doctor.sh` require Telegram values. |
| `DOCTOR_NETWORK` | `false` | Placeholder flag for future network diagnostics. |
