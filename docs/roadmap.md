# Roadmap

## Phase 0: Operational Scaffold

- Add `.env.example`, Docker, Compose, Make targets, scripts, and docs.
- Keep dry-run and paper mode as defaults.
- Define configuration names before application modules depend on them.

## Phase 1: Market Data and Signal MVP

- Implement provider connectors for selected exchanges or data APIs.
- Normalize candles and tickers into stable internal models.
- Generate first deterministic signal candidates.
- Persist signal audit records.

## Phase 2: Telegram Alerting

- Implement Telegram notifier.
- Add message templates with symbol, direction, confidence, timeframe, and risk notes.
- Add alert deduplication and rate limiting.
- Add smoke tests for notification formatting.

## Phase 3: Safety, Backtesting, and Evaluation

- Enforce confidence thresholds and cooldown windows.
- Add backtest runner and fixtures.
- Record false positives, missed moves, and noisy regimes.
- Produce daily summary reports.

## Phase 4: Paper Execution Readiness

- Add paper-trade ledger and position simulation.
- Validate slippage, fees, stop logic, and risk sizing.
- Require explicit review before setting `ALLOW_LIVE_TRADING=true`.

## Phase 5: Hardened Deployment

- Add metrics and a real health endpoint or command.
- Add structured JSON logs.
- Add secret-manager integration.
- Add backup and restore procedure for local state.
- Add release checklist and rollback procedure.
