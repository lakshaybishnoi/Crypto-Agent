from datetime import UTC, date, datetime

from crypto_agent.core.models import MarketSignal, SignalAction
from crypto_agent.reports import (
    DailyReport,
    DailyReportBuilder,
    PnLSummary,
    TradeSummary,
    build_daily_report,
)


def test_daily_report_builder_formats_signals_trades_and_pnl() -> None:
    signal = MarketSignal(
        symbol="BTCUSDT",
        action=SignalAction.BUY,
        confidence=0.78,
        timeframe="15m",
        entry=61800.0,
        stop_loss=60900.0,
        take_profit=[63200.0, 64000.0],
        reason="Momentum confirmed by trend and sentiment.",
        risk_level="medium",
        created_at=datetime(2026, 7, 9, tzinfo=UTC),
    )
    trade = TradeSummary(
        symbol="BTCUSDT",
        side="long",
        quantity=0.25,
        entry=61800.0,
        exit=62320.0,
        pnl=125.5,
        fees=2.5,
    )
    pnl = PnLSummary(
        realized=125.5,
        unrealized=-3.0,
        fees=2.5,
        starting_equity=10_000.0,
        ending_equity=10_120.0,
    )

    message = DailyReportBuilder().build(
        DailyReport(
            report_date=date(2026, 7, 9),
            signals=[signal],
            trades=[trade],
            pnl=pnl,
            notes=["Dry run only."],
        )
    )

    assert "*Daily Crypto Report - 2026-07-09*" in message
    assert "Signals: 1 total (BUY 1); 1 actionable, 0 suppressed" in message
    assert "BTCUSDT BUY 78% 15m | entry 61,800" in message
    assert "targets 63,200, 64,000" in message
    assert "Trades: 1 recorded; 1 closed, 0 open; win rate 100% (1/1)" in message
    assert "PnL: realized +$125.50, unrealized -$3.00, fees $2.50, net +$120.00" in message
    assert "Equity: $10,000.00 -> $10,120.00 (+1.20%)" in message
    assert "Dry run only." in message


def test_daily_report_accepts_mapping_inputs_and_fits_telegram_limit() -> None:
    long_note = " ".join(["watch liquidity around resistance"] * 40)

    message = DailyReportBuilder(max_chars=420).build(
        {
            "report_date": "2026-07-09",
            "signals": [
                {
                    "symbol": "ETH_USDT",
                    "action": "sell",
                    "confidence": 64,
                    "timeframe": "5m",
                    "entry_price": "3400",
                    "stop": "3460",
                    "targets": "3320, 3280",
                    "risk": "high",
                    "reason": "Mean reversion *risk* [watch].",
                }
            ],
            "trades": [
                {
                    "symbol": "ETHUSDT",
                    "side": "short",
                    "status": "closed",
                    "quantity": "0.5",
                    "entry": "3400",
                    "exit": "3360",
                    "realized_pnl": "18.75",
                    "fees": "1.25",
                }
            ],
            "pnl": {"realized_pnl": "18.75", "fees": "1.25", "currency": "USDT"},
            "notes": [long_note],
        }
    )

    assert len(message) <= 420
    assert "ETH\\_USDT SELL 64% 5m" in message
    assert "PnL: realized +USDT 18.75" in message
    assert "...truncated for Telegram..." in message


def test_build_daily_report_computes_pnl_from_trades_when_not_supplied() -> None:
    message = build_daily_report(
        report_date=date(2026, 7, 9),
        trades=[
            {"symbol": "SOLUSDT", "side": "long", "status": "closed", "pnl": "15.25"},
            {
                "symbol": "ETHUSDT",
                "side": "long",
                "entry_price": "100",
                "exit_price": "110",
                "pnl": "5.00",
                "entry_fee": "0.25",
                "exit_fee": "0.25",
            },
            {"symbol": "SOLUSDT", "side": "long", "status": "open", "pnl": "-2.00"},
        ],
    )

    assert "Signals: 0 total; no signal activity" in message
    assert "Trades: 3 recorded; 2 closed, 1 open; win rate 100% (2/2)" in message
    assert "ETHUSDT LONG closed | qty n/a | entry 100 | exit 110 | PnL +$5.00" in message
    assert "PnL: realized +$20.25, unrealized -$2.00, fees $0.50, net +$17.75" in message
