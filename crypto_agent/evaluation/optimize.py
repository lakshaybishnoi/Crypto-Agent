"""Walk-forward search over entry filters and exit geometry.

Hit rate is jointly determined by entry quality and exit geometry: with a target
at R times the stop distance, a driftless random walk already wins with
probability 1/(1+R). A config is only interesting if its hit rate beats that
geometric baseline by enough to be profitable after costs. This module searches
the grid on a training window and reports honest out-of-sample results on a
held-out test window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import product
from math import sqrt

from crypto_agent.analysis.indicators import adx, atr, ema
from crypto_agent.core.models import Candle, SignalAction
from crypto_agent.signals.engine import SignalEngine, SignalEngineConfig

DEFAULT_THRESHOLDS = (0.45, 0.55, 0.65, 0.75, 0.85)
DEFAULT_STOP_ATRS = (1.0, 1.5, 2.0, 2.5, 3.0)
DEFAULT_TARGET_RS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)
DEFAULT_REGIMES = (None, "trending", "ranging")


@dataclass(frozen=True, slots=True)
class Candidate:
    """One potential signal: a candle where the composite score was non-zero."""

    symbol: str
    at: datetime
    direction: int  # +1 buy, -1 sell
    confidence: float
    regime: str
    htf_agrees: bool
    entry: float
    atr: float
    index: int


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    min_confidence: float
    regime: str | None
    stop_atr: float
    target_r: float

    @property
    def geometric_baseline(self) -> float:
        """Hit rate a random entry achieves with this target/stop ratio."""
        return 1.0 / (1.0 + self.target_r)

    def describe(self) -> str:
        regime = self.regime or "any"
        return (
            f"conf>={self.min_confidence:.2f} regime={regime} "
            f"stop={self.stop_atr:.1f}xATR target={self.target_r:.2f}R"
        )


@dataclass(frozen=True, slots=True)
class ConfigResult:
    config: StrategyConfig
    n: int
    wins: int
    losses: int
    expired: int
    avg_return_pct: float
    return_se: float = 0.0  # standard error of the per-trade return mean

    @property
    def decided(self) -> int:
        return self.wins + self.losses

    @property
    def expectancy_lower_bound(self) -> float:
        """One-sided 95% lower bound on the mean per-trade return."""
        return self.avg_return_pct - 1.645 * self.return_se

    @property
    def hit_rate(self) -> float | None:
        return self.wins / self.decided if self.decided else None

    @property
    def wilson_lower_bound(self) -> float:
        """95% lower confidence bound on the hit rate."""
        n = self.decided
        if n == 0:
            return 0.0
        z = 1.96
        phat = self.wins / n
        denominator = 1 + z * z / n
        centre = phat + z * z / (2 * n)
        margin = z * sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
        return (centre - margin) / denominator

    @property
    def edge_over_baseline(self) -> float | None:
        if self.hit_rate is None:
            return None
        return self.hit_rate - self.config.geometric_baseline


def generate_candidates(
    candles: list[Candle],
    higher: list[Candle] | None,
    *,
    engine_config: SignalEngineConfig | None = None,
    min_confidence: float = 0.40,
    history_window: int = 500,
) -> list[Candidate]:
    """One replay pass recording every candle whose composite score cleared the floor."""
    base = engine_config or SignalEngineConfig()
    permissive = SignalEngineConfig(
        minimum_confidence=1e-9,
        watch_confidence=0.0,
        cooldown_seconds=0,
        technical_weight=base.technical_weight,
        volume_weight=base.volume_weight,
        news_weight=base.news_weight,
        social_weight=base.social_weight,
        minimum_candles=base.minimum_candles,
        adx_trend_threshold=base.adx_trend_threshold,
        adx_range_threshold=base.adx_range_threshold,
    )
    engine = SignalEngine(permissive)

    ordered = sorted(candles, key=lambda candle: candle.open_time)
    atr_series = atr(ordered, 14)
    adx_series = adx(ordered, 14)
    higher_trends = _higher_trend_by_base_index(ordered, higher)

    candidates: list[Candidate] = []
    for index, candle in enumerate(ordered):
        window_start = max(0, index + 1 - history_window)
        history = ordered[window_start : index + 1]
        if len(history) < permissive.minimum_candles:
            continue
        now = candle.close_time or candle.open_time
        signal = engine.evaluate(
            candle.symbol,
            history,
            timeframe=candle.timeframe,
            now=now,
        )
        if signal.action not in {SignalAction.BUY, SignalAction.SELL}:
            continue
        if signal.confidence < min_confidence:
            continue
        atr_value = atr_series[index]
        if atr_value is None or atr_value <= 0:
            atr_value = max(abs(candle.close) * 0.01, 1e-9)
        direction = 1 if signal.action == SignalAction.BUY else -1
        higher_trend = higher_trends[index]
        candidates.append(
            Candidate(
                symbol=candle.symbol.upper(),
                at=now,
                direction=direction,
                confidence=signal.confidence,
                regime=_regime_label(
                    adx_series[index], base.adx_range_threshold, base.adx_trend_threshold
                ),
                htf_agrees=higher_trend is None or higher_trend * direction > 0,
                entry=candle.close,
                atr=atr_value,
                index=index,
            )
        )
    return candidates


def label_candidates(
    ordered: list[Candle],
    candidates: list[Candidate],
    geometries: list[tuple[float, float]],
    *,
    max_bars: int = 96,
) -> dict[tuple[float, float], list[tuple[str, float]]]:
    """Outcome per candidate per (stop_atr, target_r): (result, pre-cost return pct)."""
    outcomes: dict[tuple[float, float], list[tuple[str, float]]] = {
        geometry: [] for geometry in geometries
    }
    for candidate in candidates:
        future = ordered[candidate.index + 1 : candidate.index + 1 + max_bars]
        for stop_mult, target_r in geometries:
            outcomes[(stop_mult, target_r)].append(
                _label_one(candidate, future, stop_mult, target_r)
            )
    return outcomes


def evaluate_config(
    candidates: list[Candidate],
    outcomes: list[tuple[str, float]],
    config: StrategyConfig,
    *,
    cooldown_seconds: int = 900,
    cost_pct: float = 0.001,
) -> ConfigResult:
    wins = losses = expired = 0
    total_return = 0.0
    total_return_sq = 0.0
    n = 0
    last_taken: dict[tuple[str, int], datetime] = {}

    for candidate, (result, ret_pct) in zip(candidates, outcomes, strict=True):
        if candidate.confidence < config.min_confidence:
            continue
        if config.regime is not None and candidate.regime != config.regime:
            continue
        if not candidate.htf_agrees:
            continue
        key = (candidate.symbol, candidate.direction)
        previous = last_taken.get(key)
        if previous is not None and candidate.at - previous < timedelta(
            seconds=cooldown_seconds
        ):
            continue
        last_taken[key] = candidate.at

        n += 1
        net = ret_pct - cost_pct
        total_return += net
        total_return_sq += net * net
        if result == "win":
            wins += 1
        elif result == "loss":
            losses += 1
        else:
            expired += 1

    mean = total_return / n if n else 0.0
    variance = max(total_return_sq / n - mean * mean, 0.0) if n else 0.0
    return ConfigResult(
        config=config,
        n=n,
        wins=wins,
        losses=losses,
        expired=expired,
        avg_return_pct=mean,
        return_se=sqrt(variance / n) if n else 0.0,
    )


@dataclass(slots=True)
class Optimizer:
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS
    stop_atrs: tuple[float, ...] = DEFAULT_STOP_ATRS
    target_rs: tuple[float, ...] = DEFAULT_TARGET_RS
    regimes: tuple[str | None, ...] = DEFAULT_REGIMES
    max_bars: int = 96
    cooldown_seconds: int = 900
    cost_pct: float = 0.001  # round-trip fees+slippage as a fraction of notional
    min_train_signals: int = 30
    target_hit_rate: float = 0.60
    rank_by: str = "hit_rate"  # "hit_rate" | "profit"
    engine_config: SignalEngineConfig = field(default_factory=SignalEngineConfig)

    def run(
        self,
        candles_by_symbol: dict[str, list[Candle]],
        higher_by_symbol: dict[str, list[Candle] | None],
        *,
        split_at: datetime,
    ) -> OptimizationReport:
        train_candidates: list[Candidate] = []
        test_candidates: list[Candidate] = []
        train_outcomes: dict[tuple[float, float], list[tuple[str, float]]] = {}
        test_outcomes: dict[tuple[float, float], list[tuple[str, float]]] = {}
        geometries = [
            (stop, target) for stop in self.stop_atrs for target in self.target_rs
        ]

        for symbol, candles in candles_by_symbol.items():
            ordered = sorted(candles, key=lambda candle: candle.open_time)
            candidates = generate_candidates(
                ordered,
                higher_by_symbol.get(symbol),
                engine_config=self.engine_config,
                min_confidence=min(self.thresholds),
            )
            labeled = label_candidates(ordered, candidates, geometries, max_bars=self.max_bars)
            for position, candidate in enumerate(candidates):
                bucket_candidates, bucket_outcomes = (
                    (train_candidates, train_outcomes)
                    if candidate.at < split_at
                    else (test_candidates, test_outcomes)
                )
                bucket_candidates.append(candidate)
                for geometry in geometries:
                    bucket_outcomes.setdefault(geometry, []).append(
                        labeled[geometry][position]
                    )

        results: list[tuple[ConfigResult, ConfigResult]] = []
        for threshold, regime, (stop, target) in product(
            self.thresholds, self.regimes, geometries
        ):
            config = StrategyConfig(
                min_confidence=threshold, regime=regime, stop_atr=stop, target_r=target
            )
            train = evaluate_config(
                train_candidates,
                train_outcomes.get((stop, target), []),
                config,
                cooldown_seconds=self.cooldown_seconds,
                cost_pct=self.cost_pct,
            )
            test = evaluate_config(
                test_candidates,
                test_outcomes.get((stop, target), []),
                config,
                cooldown_seconds=self.cooldown_seconds,
                cost_pct=self.cost_pct,
            )
            results.append((train, test))

        if self.rank_by == "profit":
            qualifying = [
                (train, test)
                for train, test in results
                if train.n >= self.min_train_signals and train.expectancy_lower_bound > 0
            ]
            sort_key = lambda pair: pair[0].expectancy_lower_bound  # noqa: E731
        else:
            qualifying = [
                (train, test)
                for train, test in results
                if train.n >= self.min_train_signals
                and train.hit_rate is not None
                and train.hit_rate >= self.target_hit_rate
                and train.avg_return_pct > 0
            ]
            sort_key = lambda pair: pair[0].wilson_lower_bound  # noqa: E731

        qualifying.sort(key=sort_key, reverse=True)
        fallback = sorted(
            (pair for pair in results if pair[0].n >= self.min_train_signals),
            key=lambda pair: (
                pair[0].expectancy_lower_bound
                if self.rank_by == "profit"
                else pair[0].wilson_lower_bound
            ),
            reverse=True,
        )
        return OptimizationReport(
            qualifying=qualifying,
            best_effort=fallback[:10],
            train_candidates=len(train_candidates),
            test_candidates=len(test_candidates),
            split_at=split_at,
            target_hit_rate=self.target_hit_rate,
            cost_pct=self.cost_pct,
            rank_by=self.rank_by,
        )


@dataclass(frozen=True, slots=True)
class OptimizationReport:
    qualifying: list[tuple[ConfigResult, ConfigResult]]
    best_effort: list[tuple[ConfigResult, ConfigResult]]
    train_candidates: int
    test_candidates: int
    split_at: datetime
    target_hit_rate: float
    cost_pct: float
    rank_by: str = "hit_rate"

    def render(self, top: int = 10) -> str:
        lines = [
            f"candidates: train={self.train_candidates} test={self.test_candidates} "
            f"(split at {self.split_at.isoformat()})",
            f"cost assumption: {self.cost_pct:.2%} round trip",
            "",
        ]
        goal = (
            "positive expectancy (95% lower bound > 0, ranked by it)"
            if self.rank_by == "profit"
            else (
                f">= {self.target_hit_rate:.0%} train hit rate with positive "
                "expectancy (ranked by hit-rate 95% lower bound)"
            )
        )
        if self.qualifying:
            lines.append(f"configs meeting {goal}, with held-out test:")
            for train, test in self.qualifying[:top]:
                lines.append(self._row(train, test))
        else:
            lines.append(f"NO config met {goal}. Best available:")
            for train, test in self.best_effort[:top]:
                lines.append(self._row(train, test))
        return "\n".join(lines)

    @staticmethod
    def _row(train: ConfigResult, test: ConfigResult) -> str:
        def stats(result: ConfigResult) -> str:
            hit = f"{result.hit_rate:.1%}" if result.hit_rate is not None else "n/a"
            return (
                f"hit={hit} (n={result.n}, exp={result.expired}) "
                f"avg_ret={result.avg_return_pct:+.3%} "
                f"ret_lb={result.expectancy_lower_bound:+.3%}"
            )

        baseline = train.config.geometric_baseline
        return (
            f"- {train.config.describe()} | baseline={baseline:.0%} | "
            f"TRAIN {stats(train)} hit_lb={train.wilson_lower_bound:.1%} | TEST {stats(test)}"
        )


def _label_one(
    candidate: Candidate,
    future: list[Candle],
    stop_mult: float,
    target_r: float,
) -> tuple[str, float]:
    stop_distance = stop_mult * candidate.atr
    entry = candidate.entry
    direction = candidate.direction
    stop = entry - direction * stop_distance
    target = entry + direction * stop_distance * target_r

    for candle in future:
        if direction > 0:
            if candle.low <= stop:
                return "loss", -stop_distance / entry
            if candle.high >= target:
                return "win", (stop_distance * target_r) / entry
        else:
            if candle.high >= stop:
                return "loss", -stop_distance / entry
            if candle.low <= target:
                return "win", (stop_distance * target_r) / entry

    if future:
        drift = direction * (future[-1].close - entry) / entry
        return "expired", drift
    return "expired", 0.0


def _regime_label(adx_value: float | None, low: float, high: float) -> str:
    if adx_value is None:
        return "unknown"
    if adx_value >= high:
        return "trending"
    if adx_value <= low:
        return "ranging"
    return "transitional"


def _higher_trend_by_base_index(
    ordered: list[Candle],
    higher: list[Candle] | None,
) -> list[float | None]:
    """Higher-timeframe EMA trend (+1/-1) as of each base candle's close, or None."""
    if not higher:
        return [None] * len(ordered)

    higher_ordered = sorted(higher, key=lambda candle: candle.open_time)
    closes = [candle.close for candle in higher_ordered]
    ema_9 = ema(closes, 9)
    ema_21 = ema(closes, 21)

    trends: list[float | None] = [None] * len(ordered)
    pointer = 0
    last_trend: float | None = None
    for index, candle in enumerate(ordered):
        now = candle.close_time or candle.open_time
        while pointer < len(higher_ordered) and (
            higher_ordered[pointer].close_time or higher_ordered[pointer].open_time
        ) <= now:
            fast, slow = ema_9[pointer], ema_21[pointer]
            if fast is not None and slow is not None and fast != slow:
                last_trend = 1.0 if fast > slow else -1.0
            pointer += 1
        trends[index] = last_trend
    return trends


__all__ = [
    "Candidate",
    "ConfigResult",
    "OptimizationReport",
    "Optimizer",
    "StrategyConfig",
    "evaluate_config",
    "generate_candidates",
    "label_candidates",
]


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="crypto_agent.evaluation.optimize",
        description="Walk-forward search for configs meeting a target hit rate.",
    )
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--days", type=float, default=90.0)
    parser.add_argument("--test-days", type=float, default=30.0)
    parser.add_argument("--target-hit-rate", type=float, default=0.60)
    parser.add_argument("--cost-bps", type=float, default=10.0, help="Round-trip cost.")
    parser.add_argument("--max-bars", type=int, default=96)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--rank",
        choices=("hit-rate", "profit"),
        default="hit-rate",
        help="hit-rate: maximize hit rate subject to >0 expectancy; profit: maximize expectancy.",
    )
    return parser


async def _run_cli(args) -> str:
    import logging

    from crypto_agent.evaluation.__main__ import resolve_confluence
    from crypto_agent.evaluation.history import candles_for_days, fetch_history

    logger = logging.getLogger(__name__)
    candles_by_symbol: dict[str, list[Candle]] = {}
    higher_by_symbol: dict[str, list[Candle] | None] = {}
    higher_timeframe = resolve_confluence(args.timeframe, "auto")

    for symbol in args.symbols:
        total = candles_for_days(args.timeframe, args.days)
        logger.info("Fetching %s %s candles for %s", total, args.timeframe, symbol)
        candles_by_symbol[symbol] = await fetch_history(symbol, args.timeframe, total)
        if higher_timeframe:
            higher_total = candles_for_days(higher_timeframe, args.days) + 50
            logger.info("Fetching %s %s candles for %s", higher_total, higher_timeframe, symbol)
            higher_by_symbol[symbol] = await fetch_history(
                symbol, higher_timeframe, higher_total
            )
        else:
            higher_by_symbol[symbol] = None

    last_time = max(
        (candles[-1].close_time or candles[-1].open_time)
        for candles in candles_by_symbol.values()
        if candles
    )
    split_at = last_time - timedelta(days=args.test_days)

    optimizer = Optimizer(
        max_bars=args.max_bars,
        cost_pct=args.cost_bps / 10_000,
        target_hit_rate=args.target_hit_rate,
        rank_by=args.rank.replace("-", "_"),
    )
    report = optimizer.run(candles_by_symbol, higher_by_symbol, split_at=split_at)
    return report.render(top=args.top)


def main() -> None:
    import asyncio
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()
    print(asyncio.run(_run_cli(args)))


if __name__ == "__main__":
    main()
