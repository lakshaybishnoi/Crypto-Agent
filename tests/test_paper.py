from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_agent.core.models import Candle, MarketSignal, SignalAction
from crypto_agent.paper import PaperTradingConfig, PaperTradingEngine, Portfolio


def candle(symbol: str = "BTCUSDT", close: float = 100.0) -> Candle:
    opened = datetime(2026, 1, 1, tzinfo=UTC)
    return Candle(
        symbol=symbol,
        open_time=opened,
        close_time=opened + timedelta(minutes=1),
        open=close,
        high=close + 2,
        low=close - 2,
        close=close,
        volume=1_000,
        timeframe="1m",
    )


def signal(
    action: SignalAction,
    symbol: str = "BTCUSDT",
    entry: float = 100.0,
    stop_loss: float | None = 95.0,
    take_profit: list[float] | None = None,
) -> MarketSignal:
    return MarketSignal(
        symbol=symbol,
        action=action,
        confidence=0.9,
        timeframe="1m",
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit or [110.0],
        reason="fixture",
        risk_level="low",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_paper_trading_engine_opens_and_closes_long_position() -> None:
    engine = PaperTradingEngine.with_config(
        PaperTradingConfig(
            initial_cash=1_000.0,
            fee_rate=0.0,
            slippage_rate=0.0,
            position_size_fraction=0.5,
        )
    )

    opened = engine.process_signal(signal(SignalAction.BUY), candle(close=100.0))
    closed = engine.process_signal(signal(SignalAction.SELL, entry=120.0), candle(close=120.0))

    assert opened.action == "opened"
    assert closed.action == "closed"
    assert engine.portfolio.active_trades == 0
    assert engine.portfolio.realized_pnl == 100.0
    assert engine.portfolio.cash == 1_100.0


def test_portfolio_enforces_duplicate_symbol_and_max_active_trades() -> None:
    portfolio = Portfolio(
        config=PaperTradingConfig(
            initial_cash=1_000.0,
            fee_rate=0.0,
            slippage_rate=0.0,
            position_size_fraction=0.2,
            max_active_trades=1,
        )
    )

    first = portfolio.process_signal(signal(SignalAction.BUY, symbol="BTCUSDT"), candle("BTCUSDT"))
    duplicate = portfolio.process_signal(
        signal(SignalAction.BUY, symbol="BTCUSDT"),
        candle("BTCUSDT"),
    )
    second_symbol = portfolio.process_signal(
        signal(SignalAction.BUY, symbol="ETHUSDT"),
        candle("ETHUSDT"),
    )

    assert first.action == "opened"
    assert duplicate.reason == "duplicate_symbol"
    assert second_symbol.reason == "max_active_trades"
    assert portfolio.active_trades == 1


def test_portfolio_processes_take_profit_from_live_candle() -> None:
    portfolio = Portfolio(
        config=PaperTradingConfig(
            initial_cash=1_000.0,
            fee_rate=0.0,
            slippage_rate=0.0,
            position_size_fraction=0.5,
        )
    )
    portfolio.process_signal(signal(SignalAction.BUY, take_profit=[105.0]), candle(close=100.0))

    event = portfolio.process_candle(candle(close=104.0))

    assert event is not None
    assert event.reason == "take_profit"
    assert portfolio.active_trades == 0
    assert portfolio.realized_pnl == 25.0
