from datetime import UTC, datetime, timedelta

from crypto_agent.core.models import (
    Candle,
    MarketSignal,
    SignalAction,
    SignalComponent,
)
from crypto_agent.storage import SQLiteStorage


def test_candle_repository_saves_and_loads_candles(tmp_path) -> None:
    base_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    candles = [
        Candle(
            symbol="BTCUSDT",
            timeframe="15m",
            open_time=base_time,
            close_time=base_time + timedelta(minutes=15),
            open=100.0,
            high=104.0,
            low=99.0,
            close=102.5,
            volume=1500.0,
        ),
        Candle(
            symbol="BTCUSDT",
            timeframe="15m",
            open_time=base_time + timedelta(minutes=15),
            close_time=base_time + timedelta(minutes=30),
            open=102.5,
            high=106.0,
            low=101.0,
            close=105.0,
            volume=1800.0,
        ),
    ]

    with SQLiteStorage(tmp_path / "agent.sqlite3") as storage:
        storage.candles.save_many(candles)

        loaded = storage.candles.list(symbol="BTCUSDT", timeframe="15m")
        latest = storage.candles.latest("BTCUSDT", timeframe="15m", limit=1)

    assert loaded == candles
    assert latest == [candles[-1]]


def test_signal_repository_saves_and_loads_market_signals(tmp_path) -> None:
    created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    signal = MarketSignal(
        symbol="ETHUSDT",
        action=SignalAction.BUY,
        confidence=0.82,
        timeframe="1h",
        entry=2500.0,
        stop_loss=2425.0,
        take_profit=[2600.0, 2725.0],
        reason="Composite view is bullish.",
        risk_level="medium",
        components=[
            SignalComponent(
                name="technical",
                score=0.75,
                weight=0.4,
                reason="EMA alignment",
            ),
            SignalComponent(
                name="volume",
                score=0.3,
                weight=0.25,
                reason="above-average volume",
            ),
        ],
        suppressed=False,
        created_at=created_at,
    )

    with SQLiteStorage(tmp_path / "agent.sqlite3") as storage:
        signal_id = storage.signals.save(signal)

        loaded = storage.signals.get(signal_id)
        latest = storage.signals.latest("ETHUSDT")

    assert loaded == signal
    assert latest == signal
