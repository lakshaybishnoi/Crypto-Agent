from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crypto_agent.core.models import Candle
from crypto_agent.evaluation.optimize import (
    Candidate,
    Optimizer,
    StrategyConfig,
    evaluate_config,
    generate_candidates,
    label_candidates,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def make_candle(index: int, close: float, *, high=None, low=None, volume=1_000.0) -> Candle:
    open_time = START + timedelta(minutes=15 * index)
    return Candle(
        symbol="BTCUSDT",
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open=close,
        high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5,
        close=close,
        volume=volume,
        timeframe="15m",
    )


def make_candidate(index: int, *, confidence=0.7, regime="trending", htf=True) -> Candidate:
    return Candidate(
        symbol="BTCUSDT",
        at=START + timedelta(minutes=15 * (index + 1)),
        direction=1,
        confidence=confidence,
        regime=regime,
        htf_agrees=htf,
        entry=100.0,
        atr=2.0,
        index=index,
    )


def test_label_candidates_win_and_loss_geometry() -> None:
    # Entry 100, ATR 2. Stop 1xATR=98, target 0.5R=101.
    candles = [make_candle(0, 100), make_candle(1, 100.5, high=101.5, low=99.5)]
    candidate = make_candidate(0)

    outcomes = label_candidates(candles, [candidate], [(1.0, 0.5), (1.0, 1.5)], max_bars=5)

    win_result, win_ret = outcomes[(1.0, 0.5)][0]
    assert win_result == "win"
    assert win_ret > 0
    # 1.5R target at 103 is never reached and stop never hit -> expired.
    expired_result, _ = outcomes[(1.0, 1.5)][0]
    assert expired_result == "expired"


def test_evaluate_config_filters_and_cooldown() -> None:
    candidates = [
        make_candidate(0, confidence=0.7),
        make_candidate(0, confidence=0.7),  # same bar: inside cooldown of previous
        make_candidate(60, confidence=0.5),  # below threshold
        make_candidate(120, confidence=0.9, regime="ranging"),  # wrong regime
        make_candidate(180, confidence=0.9, htf=False),  # HTF disagrees
        make_candidate(240, confidence=0.9),
    ]
    outcomes = [("win", 0.01)] * len(candidates)
    config = StrategyConfig(min_confidence=0.6, regime="trending", stop_atr=1.0, target_r=1.0)

    result = evaluate_config(candidates, outcomes, config, cost_pct=0.001)

    assert result.n == 2
    assert result.wins == 2
    assert result.hit_rate == 1.0
    assert result.avg_return_pct == 0.01 - 0.001


def test_strategy_config_geometric_baseline() -> None:
    assert StrategyConfig(0.5, None, 1.0, 1.0).geometric_baseline == 0.5
    assert abs(StrategyConfig(0.5, None, 1.0, 0.5).geometric_baseline - 2 / 3) < 1e-9


def test_generate_candidates_and_optimizer_smoke() -> None:
    candles = []
    price = 100.0
    for index in range(220):
        step = 1.0 if (index // 40) % 2 == 0 else -1.0
        price += step
        candles.append(
            Candle(
                symbol="BTCUSDT",
                open_time=START + timedelta(minutes=15 * index),
                close_time=START + timedelta(minutes=15 * (index + 1)),
                open=price - step / 2,
                high=price + 1.2,
                low=price - 1.2,
                close=price,
                volume=1_000 + (index % 40) * 30,
                timeframe="15m",
            )
        )

    candidates = generate_candidates(candles, None, min_confidence=0.05)
    assert candidates, "zig-zag fixture should produce scored candidates"
    assert all(candidate.direction in (-1, 1) for candidate in candidates)

    optimizer = Optimizer(
        thresholds=(0.05, 0.3),
        stop_atrs=(1.0, 2.0),
        target_rs=(0.5, 1.0),
        regimes=(None,),
        min_train_signals=1,
        max_bars=20,
    )
    split_at = START + timedelta(minutes=15 * 160)
    report = optimizer.run({"BTCUSDT": candles}, {"BTCUSDT": None}, split_at=split_at)

    assert report.train_candidates + report.test_candidates == len(candidates)
    rendered = report.render()
    assert "candidates: train=" in rendered
    assert "TRAIN" in rendered
