# Phase 2: Reporting, Paper Mode, Backtests, and Persistence

Phase 2 keeps the agent in paper mode by default while adding operator-ready summaries. The
daily report builder lives in `crypto_agent.reports` and renders compact Markdown text that can be
sent through the existing Telegram notifier.

## Paper Mode

1. Copy and edit local configuration:

   ```sh
   cp .env.example .env
   ```

2. Keep the runtime safe defaults enabled:

   ```sh
   CRYPTO_AGENT_MODE=paper
   SAFETY_DRY_RUN=true
   ALLOW_LIVE_TRADING=false
   TELEGRAM_ENABLED=false
   ```

3. Validate and run the API service:

   ```sh
   make doctor
   make run
   ```

4. Run the live monitoring worker instead of the API service when you want paper signals from the
   market stream:

   ```sh
   CRYPTO_AGENT_CMD="python3 -m crypto_agent.runner" make run
   ```

Telegram can be enabled for a controlled smoke test after the bot token and chat id are set. Keep
`SAFETY_DRY_RUN=true` during that test.

The paper engine can also be driven directly from signals and candles in integration jobs:

```python
from crypto_agent.paper import PaperTradingConfig, PaperTradingEngine

engine = PaperTradingEngine.with_config(
    PaperTradingConfig(initial_cash=10_000, fee_rate=0.001, slippage_rate=0.0005)
)
event = engine.process_signal(signal, candle)
snapshot = engine.snapshot()
```

Use `snapshot.realized_pnl`, `snapshot.unrealized_pnl`, `snapshot.equity`, and
`snapshot.active_trades` when building the daily report.

The API exposes the live paper state when the FastAPI service is running:

```sh
curl http://127.0.0.1:8000/paper/portfolio
curl http://127.0.0.1:8000/paper/trades
```

## Daily Reports

The report builder accepts current `MarketSignal` objects plus plain dictionaries from paper,
backtest, or persistence layers.

```python
from datetime import date

from crypto_agent.reports import DailyReportBuilder, PnLSummary, TradeSummary, build_daily_report

text = build_daily_report(
    report_date=date.today(),
    signals=signals,
    trades=[
        TradeSummary(symbol="BTCUSDT", side="long", status="closed", pnl=42.5, fees=1.2)
    ],
    pnl=PnLSummary(realized=42.5, fees=1.2, starting_equity=10_000, ending_equity=10_041.3),
    notes=["Paper mode only."],
)
```

Send the resulting `text` with `TelegramNotifier.send_message(text)`. The builder keeps messages
under Telegram's message size limit and truncates at line boundaries when needed.

## Backtests

Use historical candles to produce the same signal, trade, and PnL shapes consumed by the daily
report builder. If candles have been persisted, you can run a backtest through the API:

```sh
curl -X POST http://127.0.0.1:8000/backtests/run \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"BTCUSDT","timeframe":"15m","candle_limit":500}'

curl http://127.0.0.1:8000/backtests/latest?symbol=BTCUSDT
```

The programmatic surface is also available:

```sh
make doctor
python3 - <<'PY'
from datetime import date

from crypto_agent.backtesting import BacktestConfig, BacktestEngine
from crypto_agent.reports import PnLSummary, build_daily_report
from crypto_agent.storage import SQLiteStorage

symbol = "BTCUSDT"
timeframe = "15m"

with SQLiteStorage("./data/crypto_agent.sqlite3") as storage:
    candles = storage.candles.list(symbol=symbol, timeframe=timeframe)

result = BacktestEngine(config=BacktestConfig(initial_cash=10_000)).run(candles)
fees = sum(trade.entry_fee + trade.exit_fee for trade in result.trades)

print(result.metrics)
print(
    build_daily_report(
        report_date=date.today(),
        trades=result.trades,
        pnl=PnLSummary(
            realized=sum(trade.pnl for trade in result.trades),
            fees=fees,
            starting_equity=result.initial_cash,
            ending_equity=result.final_equity,
        ),
        notes=[f"Backtest {symbol} {timeframe}"],
    )
)
PY
```

When a backtest runner writes JSON or database rows, include these fields so the report can render
without adapters:

- signals: `symbol`, `action`, `confidence`, `timeframe`, `entry`, `stop_loss`, `take_profit`,
  `reason`, `risk_level`, `suppressed`
- trades: `symbol`, `side`, `status`, `quantity`, `entry`, `exit`, `pnl`, `fees`
- pnl: `realized`, `unrealized`, `fees`, `currency`, `starting_equity`, `ending_equity`,
  `open_positions`

Use `BacktestResult.as_dict()` for metrics snapshots when storing or exporting a completed replay.

## Persistence

Local persistence is configured through:

```sh
DATA_DIR=./data
LOG_DIR=./logs
SQLITE_PATH=./data/crypto_agent.sqlite3
DATABASE_URL=postgresql+asyncpg://crypto:crypto@postgres:5432/crypto_agent
REDIS_URL=redis://redis:6379/0
```

For single-process local development, prefer SQLite under `./data`. For the Compose stack, Postgres
and Redis are started with:

```sh
make up
make logs
make down
```

Persist raw market inputs, generated signals, paper ledger rows, and daily report text with
timestamps. That gives operators enough audit history to compare live paper results with backtest
evidence without enabling live trading.

The local repository wrapper initializes schema automatically:

```python
from crypto_agent.storage import BacktestResult, PaperTrade, SQLiteStorage

with SQLiteStorage("./data/crypto_agent.sqlite3") as storage:
    storage.candles.save_many(candles)
    signal_id = storage.signals.save(signal)
    storage.paper_trades.save(
        PaperTrade(
            symbol="BTCUSDT",
            side="long",
            quantity=1,
            entry_price=1,
            opened_at=opened_at,
        )
    )
    storage.backtests.save(
        BacktestResult(
            strategy="signal-engine",
            symbol="BTCUSDT",
            timeframe="15m",
            started_at=started_at,
            ended_at=ended_at,
            metrics=result.metrics,
        )
    )
```
