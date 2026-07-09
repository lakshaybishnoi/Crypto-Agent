from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_agent.core.models import Candle, MarketSignal, SentimentSnapshot, SignalAction
from crypto_agent.evaluation import (
    EvaluationHarness,
    OutcomeTracker,
    label_outcomes,
    render_report,
    signed_return,
)
from crypto_agent.signals.engine import SignalEngineConfig
from crypto_agent.storage import SQLiteStorage

START = datetime(2026, 1, 1, tzinfo=UTC)


def make_candle(
    index: int,
    close: float,
    *,
    symbol: str = "BTCUSDT",
    high: float | None = None,
    low: float | None = None,
    volume: float = 1_000.0,
) -> Candle:
    open_time = START + timedelta(minutes=index)
    return Candle(
        symbol=symbol,
        open_time=open_time,
        close_time=open_time + timedelta(seconds=59),
        open=close,
        high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5,
        close=close,
        volume=volume,
        timeframe="1m",
    )


def make_signal(
    action: SignalAction,
    *,
    created_at: datetime,
    entry: float = 100.0,
    stop_loss: float = 95.0,
    take_profit: float = 105.0,
) -> MarketSignal:
    return MarketSignal(
        symbol="BTCUSDT",
        action=action,
        confidence=0.7,
        timeframe="1m",
        entry=entry,
        stop_loss=stop_loss,
        take_profit=[take_profit],
        reason="fixture",
        risk_level="low",
        created_at=created_at,
    )


class TestSignedReturn:
    def test_buy_return_is_positive_when_price_rises(self):
        assert signed_return("buy", 100.0, 110.0) == 0.1

    def test_sell_return_is_positive_when_price_falls(self):
        assert signed_return("sell", 100.0, 90.0) == 0.1


class TestLabelOutcomes:
    def test_buy_take_profit_hit(self):
        signal = make_signal(SignalAction.BUY, created_at=make_candle(0, 100).close_time)
        candles = [make_candle(0, 100), make_candle(1, 102), make_candle(2, 104, high=106)]

        outcomes = label_outcomes([signal], candles, max_bars=10, horizons=(1,))

        assert len(outcomes) == 1
        assert outcomes[0].outcome == "take_profit"
        assert outcomes[0].exit_price == 105.0
        assert outcomes[0].bars_to_resolution == 2
        assert outcomes[0].return_pct is not None and outcomes[0].return_pct > 0

    def test_buy_stop_loss_checked_before_target_in_same_candle(self):
        signal = make_signal(SignalAction.BUY, created_at=make_candle(0, 100).close_time)
        candles = [make_candle(0, 100), make_candle(1, 100, high=106, low=94)]

        outcomes = label_outcomes([signal], candles, max_bars=10, horizons=())

        assert outcomes[0].outcome == "stop_loss"
        assert outcomes[0].exit_price == 95.0

    def test_sell_take_profit_hit(self):
        signal = make_signal(
            SignalAction.SELL,
            created_at=make_candle(0, 100).close_time,
            stop_loss=105.0,
            take_profit=95.0,
        )
        candles = [make_candle(0, 100), make_candle(1, 96, low=94)]

        outcomes = label_outcomes([signal], candles, max_bars=10, horizons=())

        assert outcomes[0].outcome == "take_profit"
        assert outcomes[0].return_pct is not None and outcomes[0].return_pct > 0

    def test_expired_when_neither_level_hit(self):
        signal = make_signal(SignalAction.BUY, created_at=make_candle(0, 100).close_time)
        candles = [make_candle(index, 100 + index * 0.1) for index in range(6)]

        outcomes = label_outcomes([signal], candles, max_bars=3, horizons=(1, 2))

        assert outcomes[0].outcome == "expired"
        assert outcomes[0].bars_to_resolution == 3
        assert set(outcomes[0].forward_returns) == {"1", "2"}

    def test_open_when_not_enough_future_candles(self):
        signal = make_signal(SignalAction.BUY, created_at=make_candle(0, 100).close_time)
        candles = [make_candle(0, 100), make_candle(1, 100.5)]

        outcomes = label_outcomes([signal], candles, max_bars=10, horizons=())

        assert outcomes[0].outcome == "open"
        assert outcomes[0].resolved_at is None

    def test_suppressed_and_hold_signals_are_skipped(self):
        hold = make_signal(SignalAction.HOLD, created_at=START)
        suppressed = MarketSignal(
            symbol="BTCUSDT",
            action=SignalAction.BUY,
            confidence=0.7,
            timeframe="1m",
            entry=100.0,
            stop_loss=95.0,
            take_profit=[105.0],
            reason="fixture",
            risk_level="low",
            suppressed=True,
            created_at=START,
        )

        outcomes = label_outcomes([hold, suppressed], [make_candle(1, 101)], max_bars=5)

        assert outcomes == []


class TestOutcomeTracker:
    def test_live_signal_resolves_on_take_profit(self):
        tracker = OutcomeTracker(max_bars=10)
        first_candle = make_candle(0, 100)
        signal = make_signal(SignalAction.BUY, created_at=datetime.now(UTC))
        tracker.track(signal, after=first_candle.open_time)

        assert tracker.on_candle(first_candle) == []
        assert tracker.pending_count("BTCUSDT") == 1

        resolved = tracker.on_candle(make_candle(1, 104, high=106))

        assert len(resolved) == 1
        assert resolved[0].outcome == "take_profit"
        assert tracker.pending_count("BTCUSDT") == 0

    def test_live_signal_expires_after_max_bars(self):
        tracker = OutcomeTracker(max_bars=2)
        signal = make_signal(SignalAction.BUY, created_at=datetime.now(UTC))
        tracker.track(signal, after=make_candle(0, 100).open_time)

        assert tracker.on_candle(make_candle(1, 100.2)) == []
        resolved = tracker.on_candle(make_candle(2, 100.4))

        assert len(resolved) == 1
        assert resolved[0].outcome == "expired"

    def test_other_timeframes_do_not_advance_tracking(self):
        tracker = OutcomeTracker(max_bars=1)
        signal = make_signal(SignalAction.BUY, created_at=datetime.now(UTC))
        tracker.track(signal, after=make_candle(0, 100).open_time)
        other_timeframe = Candle(
            symbol="BTCUSDT",
            open_time=START + timedelta(minutes=15),
            open=100,
            high=120,
            low=80,
            close=100,
            volume=1.0,
            timeframe="15m",
        )

        assert tracker.on_candle(other_timeframe) == []
        assert tracker.pending_count("BTCUSDT") == 1


class TestEvaluationHarness:
    def test_offline_replay_produces_labeled_report(self):
        candles = []
        price = 100.0
        for index in range(120):
            price += 1.0
            candles.append(
                Candle(
                    symbol="BTCUSDT",
                    open_time=START + timedelta(minutes=index),
                    close_time=START + timedelta(minutes=index, seconds=59),
                    open=price - 0.5,
                    high=price + 1.0,
                    low=price - 1.0,
                    close=price,
                    volume=1_000 + index * 25,
                    timeframe="1m",
                )
            )
        harness = EvaluationHarness(
            engine_config=SignalEngineConfig(
                minimum_confidence=0.2,
                watch_confidence=0.1,
                cooldown_seconds=0,
                minimum_candles=20,
            ),
            max_bars=12,
            horizons=(1, 4),
        )
        sentiment = SentimentSnapshot(
            source="fixture", score=1.0, confidence=1.0, reason="bullish"
        )

        evaluation = harness.evaluate_candles(candles, news=sentiment, social=sentiment)

        assert evaluation.symbol == "BTCUSDT"
        assert evaluation.candle_count == 120
        assert evaluation.actionable > 0
        assert evaluation.wins + evaluation.losses + evaluation.expired > 0
        assert evaluation.hit_rate is None or 0.0 <= evaluation.hit_rate <= 1.0
        assert evaluation.backtest_metrics["trade_count"] >= 0

        report = render_report([evaluation])
        assert "BTCUSDT 1m" in report
        assert "hit rate" in report


class TestSignalOutcomeStorage:
    def test_round_trip_and_hit_rate(self):
        storage = SQLiteStorage(":memory:")
        signal = make_signal(SignalAction.BUY, created_at=make_candle(0, 100).close_time)
        win_candles = [make_candle(0, 100), make_candle(1, 104, high=106)]
        loss_candles = [make_candle(0, 100), make_candle(1, 96, low=94)]
        for candles in (win_candles, loss_candles):
            for outcome in label_outcomes([signal], candles, max_bars=5, horizons=(1,)):
                storage.signal_outcomes.save(outcome)

        stored = storage.signal_outcomes.list("BTCUSDT")
        summary = storage.signal_outcomes.hit_rate("BTCUSDT", "1m")

        assert len(stored) == 2
        assert stored[0].forward_returns
        assert summary["decided"] == 2
        assert summary["wins"] == 1
        assert summary["hit_rate"] == 0.5
        storage.close()
