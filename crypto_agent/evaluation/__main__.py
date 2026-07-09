"""CLI entry point: evaluate signal accuracy over recent Binance history.

Usage:
    python -m crypto_agent.evaluation --symbols BTCUSDT ETHUSDT --timeframes 15m --days 30
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from crypto_agent.config import get_settings
from crypto_agent.core.timeframes import TIMEFRAME_SECONDS, timeframe_seconds
from crypto_agent.evaluation.harness import EvaluationHarness, SymbolEvaluation, render_report
from crypto_agent.evaluation.history import candles_for_days, fetch_history
from crypto_agent.signals.engine import SignalEngineConfig

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto_agent.evaluation",
        description="Replay recent market history and report signal accuracy.",
    )
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--timeframes", nargs="+", default=["15m"])
    parser.add_argument("--days", type=float, default=30.0)
    parser.add_argument(
        "--candles", type=int, default=None, help="Override --days with an exact candle count."
    )
    parser.add_argument(
        "--max-bars",
        type=int,
        default=96,
        help="Bars to wait for stop/target before a signal expires.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Override the configured alert threshold for this run.",
    )
    parser.add_argument(
        "--store",
        action="store_true",
        help="Persist labeled outcomes to the configured SQLite database.",
    )
    parser.add_argument(
        "--confluence",
        default="auto",
        help=(
            "Higher timeframe for trend-veto confluence: a timeframe like 1h, "
            "'auto' (>=4x the base timeframe), or 'none' to disable."
        ),
    )
    return parser


def resolve_confluence(base_timeframe: str, choice: str) -> str | None:
    if choice == "none":
        return None
    if choice != "auto":
        timeframe_seconds(choice)  # validate
        return choice
    base = timeframe_seconds(base_timeframe)
    larger = [
        (seconds, name) for name, seconds in TIMEFRAME_SECONDS.items() if seconds >= base * 4
    ]
    return min(larger)[1] if larger else None


async def run(args: argparse.Namespace) -> str:
    settings = get_settings()
    engine_config = SignalEngineConfig(
        minimum_confidence=(
            args.min_confidence
            if args.min_confidence is not None
            else settings.minimum_confidence
        ),
        cooldown_seconds=settings.signal_cooldown_seconds,
        regime_filter=settings.regime_filter or None,
    )
    harness = EvaluationHarness(
        engine_config=engine_config,
        stop_atr_multiplier=settings.stop_atr_multiplier,
        target_r_multiple=settings.target_r_multiple,
        max_bars=args.max_bars,
    )

    evaluations: list[SymbolEvaluation] = []
    for symbol in args.symbols:
        for timeframe in args.timeframes:
            total = args.candles or candles_for_days(timeframe, args.days)
            LOGGER.info("Fetching %s candles for %s %s", total, symbol, timeframe)
            candles = await fetch_history(symbol, timeframe, total)
            if not candles:
                LOGGER.warning("No history returned for %s %s; skipping", symbol, timeframe)
                continue
            higher = None
            higher_timeframe = resolve_confluence(timeframe, args.confluence)
            if higher_timeframe:
                higher_total = candles_for_days(higher_timeframe, args.days) + 50
                LOGGER.info(
                    "Fetching %s confluence candles (%s) for %s",
                    higher_total,
                    higher_timeframe,
                    symbol,
                )
                higher = await fetch_history(symbol, higher_timeframe, higher_total)
            evaluations.append(
                harness.evaluate_candles(candles, higher_timeframe_candles=higher)
            )

    if args.store and evaluations:
        _store_outcomes(evaluations, settings.sqlite_path)

    return render_report(evaluations)


def _store_outcomes(evaluations: list[SymbolEvaluation], sqlite_path: str) -> None:
    from crypto_agent.storage import SQLiteStorage

    with SQLiteStorage(sqlite_path) as storage:
        saved = 0
        for evaluation in evaluations:
            for outcome in evaluation.outcomes:
                storage.signal_outcomes.save(outcome)
                saved += 1
    LOGGER.info("Stored %s labeled outcomes to %s", saved, sqlite_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    print(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
