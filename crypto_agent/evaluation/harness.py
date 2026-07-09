"""Replay historical candles and score how accurate the signal engine was."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean

from crypto_agent.backtesting import BacktestConfig, BacktestEngine
from crypto_agent.core.models import Candle, MarketSignal, SentimentSnapshot
from crypto_agent.evaluation.outcomes import (
    ACTIONABLE_ACTIONS,
    SignalOutcome,
    label_outcomes,
)
from crypto_agent.signals.engine import SignalEngine, SignalEngineConfig
from crypto_agent.signals.risk import RiskManager


@dataclass(frozen=True, slots=True)
class SymbolEvaluation:
    """Accuracy report for one symbol and timeframe."""

    symbol: str
    timeframe: str
    candle_count: int
    action_counts: dict[str, int]
    outcomes: list[SignalOutcome]
    backtest_metrics: dict[str, float | int]

    @property
    def actionable(self) -> int:
        return len(self.outcomes)

    @property
    def wins(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.is_win)

    @property
    def losses(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.is_loss)

    @property
    def expired(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.outcome == "expired")

    @property
    def unresolved(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.outcome == "open")

    @property
    def hit_rate(self) -> float | None:
        decided = self.wins + self.losses
        return self.wins / decided if decided else None

    def hit_rate_for(self, action: str) -> float | None:
        wins = sum(1 for o in self.outcomes if o.action == action and o.is_win)
        losses = sum(1 for o in self.outcomes if o.action == action and o.is_loss)
        decided = wins + losses
        return wins / decided if decided else None

    @property
    def average_win_confidence(self) -> float | None:
        values = [outcome.confidence for outcome in self.outcomes if outcome.is_win]
        return fmean(values) if values else None

    @property
    def average_loss_confidence(self) -> float | None:
        values = [outcome.confidence for outcome in self.outcomes if outcome.is_loss]
        return fmean(values) if values else None

    @property
    def average_return_pct(self) -> float | None:
        values = [
            outcome.return_pct for outcome in self.outcomes if outcome.return_pct is not None
        ]
        return fmean(values) if values else None

    @property
    def confidence_buckets(self) -> list[dict[str, object]]:
        """Hit rate per 0.05-wide confidence bucket, over decided outcomes only."""
        buckets: dict[float, list[SignalOutcome]] = {}
        for outcome in self.outcomes:
            if outcome.outcome not in {"take_profit", "stop_loss"}:
                continue
            floor = int(outcome.confidence * 20) / 20
            buckets.setdefault(floor, []).append(outcome)
        return [
            {
                "bucket": f"{floor:.2f}-{floor + 0.05:.2f}",
                "decided": len(items),
                "wins": sum(1 for item in items if item.is_win),
                "hit_rate": sum(1 for item in items if item.is_win) / len(items),
            }
            for floor, items in sorted(buckets.items())
        ]

    @property
    def forward_return_means(self) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        for outcome in self.outcomes:
            for horizon, value in outcome.forward_returns.items():
                buckets.setdefault(horizon, []).append(value)
        return {
            horizon: fmean(values)
            for horizon, values in sorted(buckets.items(), key=lambda kv: int(kv[0]))
        }

    def summary(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candles": self.candle_count,
            "actions": self.action_counts,
            "actionable_signals": self.actionable,
            "wins": self.wins,
            "losses": self.losses,
            "expired": self.expired,
            "unresolved": self.unresolved,
            "hit_rate": self.hit_rate,
            "buy_hit_rate": self.hit_rate_for("buy"),
            "sell_hit_rate": self.hit_rate_for("sell"),
            "avg_win_confidence": self.average_win_confidence,
            "avg_loss_confidence": self.average_loss_confidence,
            "avg_return_pct": self.average_return_pct,
            "forward_return_means": self.forward_return_means,
            "confidence_buckets": self.confidence_buckets,
            "backtest": self.backtest_metrics,
        }


@dataclass(slots=True)
class EvaluationHarness:
    """Replays candles through a fresh engine and labels every actionable signal."""

    engine_config: SignalEngineConfig = field(default_factory=SignalEngineConfig)
    backtest_config: BacktestConfig = field(default_factory=BacktestConfig)
    stop_atr_multiplier: float = 1.5
    target_r_multiple: float = 1.5
    max_bars: int = 96
    horizons: tuple[int, ...] = (1, 4, 12, 24)
    history_window: int = 500

    def _build_engine(self) -> SignalEngine:
        return SignalEngine(
            self.engine_config,
            risk_manager=RiskManager(
                stop_atr_multiplier=self.stop_atr_multiplier,
                target_multipliers=(self.target_r_multiple, self.target_r_multiple * 2),
            ),
        )

    def evaluate_candles(
        self,
        candles: list[Candle],
        *,
        news: SentimentSnapshot | None = None,
        social: SentimentSnapshot | None = None,
        higher_timeframe_candles: list[Candle] | None = None,
    ) -> SymbolEvaluation:
        ordered = sorted(candles, key=lambda candle: candle.open_time)
        symbol = ordered[0].symbol.upper() if ordered else "UNKNOWN"
        timeframe = ordered[0].timeframe if ordered else "unknown"

        signals = self._replay_signals(
            ordered,
            news=news,
            social=social,
            higher=sorted(higher_timeframe_candles, key=lambda candle: candle.open_time)
            if higher_timeframe_candles
            else [],
        )
        action_counts: dict[str, int] = {}
        for signal in signals:
            action_counts[signal.action.value] = action_counts.get(signal.action.value, 0) + 1

        outcomes = label_outcomes(
            signals, ordered, max_bars=self.max_bars, horizons=self.horizons
        )
        backtest = BacktestEngine(
            signal_engine=self._build_engine(),
            config=self.backtest_config,
        ).run(ordered, news=news, social=social)

        return SymbolEvaluation(
            symbol=symbol,
            timeframe=timeframe,
            candle_count=len(ordered),
            action_counts=action_counts,
            outcomes=outcomes,
            backtest_metrics=dict(backtest.metrics),
        )

    def _replay_signals(
        self,
        ordered: list[Candle],
        *,
        news: SentimentSnapshot | None,
        social: SentimentSnapshot | None,
        higher: list[Candle],
    ) -> list[MarketSignal]:
        engine = self._build_engine()
        signals: list[MarketSignal] = []
        higher_closed = 0
        for index, candle in enumerate(ordered):
            window_start = max(0, index + 1 - self.history_window)
            history = ordered[window_start : index + 1]
            if len(history) < self.engine_config.minimum_candles:
                continue
            now = candle.close_time or candle.open_time
            while higher_closed < len(higher) and (
                higher[higher_closed].close_time or higher[higher_closed].open_time
            ) <= now:
                higher_closed += 1
            higher_history = (
                higher[max(0, higher_closed - self.history_window) : higher_closed]
                if higher_closed >= 21
                else None
            )
            signal = engine.evaluate(
                candle.symbol,
                history,
                news=news,
                social=social,
                timeframe=candle.timeframe,
                now=now,
                higher_timeframe_candles=higher_history,
            )
            signals.append(signal)
        return signals


def render_report(evaluations: list[SymbolEvaluation]) -> str:
    """Render a plain-text accuracy report for one or more evaluations."""
    lines: list[str] = []
    for evaluation in evaluations:
        lines.append(f"=== {evaluation.symbol} {evaluation.timeframe} ===")
        lines.append(f"candles evaluated: {evaluation.candle_count}")
        lines.append(f"actions: {evaluation.action_counts or 'none'}")
        lines.append(
            "actionable signals: "
            f"{evaluation.actionable} "
            f"(wins={evaluation.wins} losses={evaluation.losses} "
            f"expired={evaluation.expired} open={evaluation.unresolved})"
        )
        lines.append(
            f"hit rate: {_pct(evaluation.hit_rate)} "
            f"(buy={_pct(evaluation.hit_rate_for('buy'))} "
            f"sell={_pct(evaluation.hit_rate_for('sell'))})"
        )
        lines.append(
            f"avg confidence: winners={_num(evaluation.average_win_confidence)} "
            f"losers={_num(evaluation.average_loss_confidence)}"
        )
        lines.append(f"avg signal return: {_pct(evaluation.average_return_pct)}")
        if evaluation.forward_return_means:
            forward = ", ".join(
                f"+{horizon} bars: {_pct(value)}"
                for horizon, value in evaluation.forward_return_means.items()
            )
            lines.append(f"mean forward returns: {forward}")
        if evaluation.confidence_buckets:
            calibration = ", ".join(
                "{bucket}: {rate} ({wins}/{decided})".format(**bucket)
                for bucket in (
                    {**entry, "rate": _pct(entry["hit_rate"])}  # type: ignore[arg-type]
                    for entry in evaluation.confidence_buckets
                )
            )
            lines.append(f"calibration: {calibration}")
        backtest = evaluation.backtest_metrics
        lines.append(
            "backtest: "
            f"return={_pct(backtest.get('total_return'))} "
            f"win_rate={_pct(backtest.get('win_rate'))} "
            f"profit_factor={_num(backtest.get('profit_factor'))} "
            f"max_drawdown={_pct(backtest.get('max_drawdown'))} "
            f"trades={backtest.get('trade_count')}"
        )
        lines.append("")

    decided_outcomes = [
        outcome
        for evaluation in evaluations
        for outcome in evaluation.outcomes
        if outcome.outcome in {"take_profit", "stop_loss"}
    ]
    if decided_outcomes and len(evaluations) > 1:
        wins = sum(1 for outcome in decided_outcomes if outcome.is_win)
        lines.append(
            f"OVERALL hit rate: {_pct(wins / len(decided_outcomes))} "
            f"({wins}/{len(decided_outcomes)} decided signals)"
        )
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def _num(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


__all__ = [
    "ACTIONABLE_ACTIONS",
    "EvaluationHarness",
    "SymbolEvaluation",
    "render_report",
]
