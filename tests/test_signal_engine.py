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


def test_missing_sentiment_does_not_dilute_confidence() -> None:
    engine = SignalEngine(SignalEngineConfig(cooldown_seconds=0))
    candles = make_trending_candles()

    without_sentiment = engine.evaluate("BTCUSDT", candles)

    sentiment_components = [
        component
        for component in without_sentiment.components
        if component.name in {"news", "social"}
    ]
    assert all(not component.has_data for component in sentiment_components)

    # Confidence must equal the technical+volume blend at full weight, not the
    # old behavior where dead sentiment feeds capped it at 0.65.
    scored = [component for component in without_sentiment.components if component.has_data]
    expected = abs(
        sum(component.weighted_score for component in scored)
        / sum(component.weight for component in scored)
    )
    assert without_sentiment.confidence == round(expected, 4)


def test_zero_confidence_sentiment_is_treated_as_missing() -> None:
    engine = SignalEngine(SignalEngineConfig(cooldown_seconds=0))
    candles = make_trending_candles()
    dead_feed = SentimentSnapshot(source="news", score=0.9, confidence=0.0, reason="no live feed")

    with_dead_feed = engine.evaluate("BTCUSDT", candles, news=dead_feed)
    without_feed = SignalEngine(SignalEngineConfig(cooldown_seconds=0)).evaluate(
        "BTCUSDT", candles
    )

    assert with_dead_feed.confidence == without_feed.confidence


def make_bearish_candles(symbol: str = "BTCUSDT", count: int = 40) -> list[Candle]:
    now = datetime.now(UTC)
    candles: list[Candle] = []
    price = 500.0
    for index in range(count):
        price -= 2.0
        candles.append(
            Candle(
                symbol=symbol,
                open_time=now + timedelta(minutes=15 * index),
                open=price + 1.0,
                high=price + 2.0,
                low=price - 2.0,
                close=price,
                volume=500,
                timeframe="15m",
            )
        )
    return candles


def test_higher_timeframe_disagreement_downgrades_to_watch() -> None:
    engine = SignalEngine(SignalEngineConfig(minimum_confidence=0.35, cooldown_seconds=0))
    candles = make_trending_candles()
    news = SentimentSnapshot(source="news", score=0.8, confidence=1, reason="positive news")
    social = SentimentSnapshot(source="social", score=0.6, confidence=1, reason="positive social")

    aligned = engine.evaluate("BTCUSDT", candles, news=news, social=social)
    vetoed = SignalEngine(
        SignalEngineConfig(minimum_confidence=0.35, cooldown_seconds=0)
    ).evaluate(
        "BTCUSDT",
        candles,
        news=news,
        social=social,
        higher_timeframe_candles=make_bearish_candles(),
    )

    assert aligned.action == SignalAction.BUY
    assert vetoed.action == SignalAction.WATCH
    assert "Higher-timeframe" in vetoed.reason


def test_technical_reason_reports_regime() -> None:
    engine = SignalEngine(SignalEngineConfig(cooldown_seconds=0))

    signal = engine.evaluate("BTCUSDT", make_trending_candles())

    technical = next(
        component for component in signal.components if component.name == "technical"
    )
    assert "trending regime" in technical.reason
    assert technical.score > 0


def test_weak_volume_does_not_push_direction() -> None:
    engine = SignalEngine(SignalEngineConfig(cooldown_seconds=0))
    now = datetime.now(UTC)
    # Falling prices on drying volume: old engine scored this -0.1 (bearish push).
    candles = []
    price = 200.0
    for index in range(60):
        price -= 0.5
        candles.append(
            Candle(
                symbol="BTCUSDT",
                open_time=now + timedelta(minutes=index),
                open=price + 0.3,
                high=price + 0.6,
                low=price - 0.6,
                close=price,
                volume=1_000 - index * 15,
                timeframe="1m",
            )
        )

    signal = engine.evaluate("BTCUSDT", candles)

    volume = next(component for component in signal.components if component.name == "volume")
    assert volume.score == 0.0
    assert volume.reason == "weak participation"


def test_regime_filter_downgrades_wrong_regime_signals() -> None:
    news = SentimentSnapshot(source="news", score=0.8, confidence=1, reason="positive news")
    social = SentimentSnapshot(source="social", score=0.6, confidence=1, reason="positive")
    candles = make_trending_candles()

    unfiltered = SignalEngine(
        SignalEngineConfig(minimum_confidence=0.35, cooldown_seconds=0)
    ).evaluate("BTCUSDT", candles, news=news, social=social)
    filtered = SignalEngine(
        SignalEngineConfig(
            minimum_confidence=0.35, cooldown_seconds=0, regime_filter="ranging"
        )
    ).evaluate("BTCUSDT", candles, news=news, social=social)

    assert unfiltered.action == SignalAction.BUY
    assert filtered.action == SignalAction.WATCH
    assert "Regime is trending, not ranging" in filtered.reason


def test_graded_trend_scores_scale_with_strength() -> None:
    def ramp(step: float) -> list[Candle]:
        now = datetime.now(UTC)
        candles = []
        price = 100.0
        for index in range(80):
            price += step
            candles.append(
                Candle(
                    symbol="BTCUSDT",
                    open_time=now + timedelta(minutes=index),
                    open=price - step / 2,
                    high=price + 1.0,
                    low=price - 1.0,
                    close=price,
                    volume=1_000,
                    timeframe="1m",
                )
            )
        return candles

    engine = SignalEngine(SignalEngineConfig(cooldown_seconds=0))
    strong = engine.evaluate("BTCUSDT", ramp(1.5))
    weak = SignalEngine(SignalEngineConfig(cooldown_seconds=0)).evaluate("BTCUSDT", ramp(0.05))

    strong_technical = next(c for c in strong.components if c.name == "technical")
    weak_technical = next(c for c in weak.components if c.name == "technical")
    assert strong_technical.score > weak_technical.score
