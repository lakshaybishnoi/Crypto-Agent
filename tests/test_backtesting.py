from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_agent.backtesting import BacktestConfig, BacktestEngine
from crypto_agent.core.models import Candle, SentimentSnapshot
from crypto_agent.signals.engine import SignalEngine, SignalEngineConfig


def make_trending_candles(symbol: str = "BTCUSDT", count: int = 80) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        price += 1.0
        candles.append(
            Candle(
                symbol=symbol,
                open_time=start + timedelta(minutes=index),
                open=price - 0.5,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=1_000 + index * 25,
                timeframe="1m",
            )
        )
    return candles


def test_backtest_engine_replays_candles_and_returns_metrics() -> None:
    signal_engine = SignalEngine(
        SignalEngineConfig(
            minimum_confidence=0.2,
            watch_confidence=0.1,
            cooldown_seconds=0,
            minimum_candles=20,
        )
    )
    engine = BacktestEngine(
        signal_engine=signal_engine,
        config=BacktestConfig(initial_cash=1_000.0, fee_rate=0.0, slippage_rate=0.0),
    )
    sentiment = SentimentSnapshot(source="fixture", score=1.0, confidence=1.0, reason="bullish")

    result = engine.run(make_trending_candles(), news=sentiment, social=sentiment)

    assert result.trade_count > 0
    assert result.total_return > 0
    assert 0 < result.win_rate <= 1.0
    assert result.profit_factor > 1.0
    assert result.metrics["trade_count"] == result.trade_count
    assert result.trades[-1].exit_reason == "end_of_backtest"


def test_backtest_engine_resets_cooldown_state_between_runs() -> None:
    signal_engine = SignalEngine(
        SignalEngineConfig(
            minimum_confidence=0.2,
            watch_confidence=0.1,
            cooldown_seconds=3_600,
            minimum_candles=20,
        )
    )
    engine = BacktestEngine(
        signal_engine=signal_engine,
        config=BacktestConfig(initial_cash=1_000.0, fee_rate=0.0, slippage_rate=0.0),
    )
    sentiment = SentimentSnapshot(source="fixture", score=1.0, confidence=1.0, reason="bullish")
    candles = make_trending_candles()

    first = engine.run(candles, news=sentiment, social=sentiment)
    second = engine.run(candles, news=sentiment, social=sentiment)

    assert first.trade_count == second.trade_count
    assert first.total_return == second.total_return


def test_backtest_engine_returns_empty_metrics_without_candles() -> None:
    engine = BacktestEngine(config=BacktestConfig(initial_cash=500.0))

    result = engine.run([])

    assert result.final_equity == 500.0
    assert result.metrics == {
        "total_return": 0.0,
        "win_rate": 0.0,
        "max_drawdown": 0.0,
        "profit_factor": 0.0,
        "trade_count": 0,
    }
