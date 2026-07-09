from datetime import UTC, datetime, timedelta

from crypto_agent.core.models import Candle, SentimentSnapshot, SignalAction
from crypto_agent.signals.engine import SignalEngine, SignalEngineConfig


def make_trending_candles(symbol: str = "BTCUSDT") -> list[Candle]:
    now = datetime.now(UTC)
    candles: list[Candle] = []
    price = 100.0
    for index in range(80):
        price += 1.2
        candles.append(
            Candle(
                symbol=symbol,
                open_time=now + timedelta(minutes=index),
                open=price - 0.8,
                high=price + 1.5,
                low=price - 1.2,
                close=price,
                volume=100 + index * 2,
                timeframe="15m",
            )
        )
    candles[-1] = Candle(
        symbol=symbol,
        open_time=candles[-1].open_time,
        open=candles[-1].open,
        high=candles[-1].high,
        low=candles[-1].low,
        close=candles[-1].close,
        volume=1000,
        timeframe="15m",
    )
    return candles


def test_signal_engine_generates_buy_signal_for_aligned_bullish_inputs() -> None:
    engine = SignalEngine(SignalEngineConfig(minimum_confidence=0.35))
    candles = make_trending_candles()
    news = SentimentSnapshot(source="news", score=0.8, confidence=1, reason="positive news")
    social = SentimentSnapshot(source="social", score=0.6, confidence=1, reason="positive social")

    signal = engine.evaluate("BTCUSDT", candles, news=news, social=social)

    assert signal.action == SignalAction.BUY
    assert signal.confidence >= 0.35
    assert signal.stop_loss is not None
    assert len(signal.take_profit) == 2


def test_signal_engine_respects_cooldown_for_duplicate_alerts() -> None:
    engine = SignalEngine(SignalEngineConfig(minimum_confidence=0.35, cooldown_seconds=900))
    candles = make_trending_candles()
    news = SentimentSnapshot(source="news", score=0.8, confidence=1, reason="positive news")
    social = SentimentSnapshot(source="social", score=0.6, confidence=1, reason="positive social")
    now = datetime.now(UTC)

    first = engine.evaluate("BTCUSDT", candles, news=news, social=social, now=now)
    second = engine.evaluate(
        "BTCUSDT", candles, news=news, social=social, now=now + timedelta(minutes=1)
    )

    assert first.suppressed is False
    assert second.suppressed is True


def test_signal_engine_holds_when_not_enough_candles() -> None:
    engine = SignalEngine()

    signal = engine.evaluate("BTCUSDT", make_trending_candles()[:10])

    assert signal.action == SignalAction.HOLD
    assert "Need at least" in signal.reason
