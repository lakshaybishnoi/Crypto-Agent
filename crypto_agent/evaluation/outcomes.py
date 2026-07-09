"""Label signal outcomes so accuracy can be measured instead of assumed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from crypto_agent.core.models import Candle, MarketSignal, SignalAction

ACTIONABLE_ACTIONS = {SignalAction.BUY, SignalAction.SELL}


@dataclass(frozen=True, slots=True)
class SignalOutcome:
    """Resolution of one actionable signal against subsequent candles."""

    symbol: str
    timeframe: str
    action: str
    confidence: float
    entry: float
    stop_loss: float | None
    take_profit: float | None
    signal_at: datetime
    outcome: str  # "take_profit" | "stop_loss" | "expired" | "open"
    resolved_at: datetime | None = None
    exit_price: float | None = None
    return_pct: float | None = None
    bars_to_resolution: int | None = None
    forward_returns: dict[str, float] = field(default_factory=dict)
    signal_id: int | None = None
    id: int | None = None

    @property
    def is_win(self) -> bool:
        return self.outcome == "take_profit"

    @property
    def is_loss(self) -> bool:
        return self.outcome == "stop_loss"


def signed_return(action: str, entry: float, price: float) -> float:
    """Direction-adjusted fractional return: positive means the signal was right."""
    if not entry:
        return 0.0
    raw = (price - entry) / entry
    return raw if action == SignalAction.BUY.value else -raw


def label_outcomes(
    signals: list[MarketSignal],
    candles: list[Candle],
    *,
    max_bars: int = 96,
    horizons: tuple[int, ...] = (1, 4, 12, 24),
) -> list[SignalOutcome]:
    """Label each actionable signal by walking the candles that followed it.

    The stop is checked before the target within a candle, matching the
    conservative assumption used by the backtester.
    """
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    outcomes: list[SignalOutcome] = []

    for signal in signals:
        if signal.action not in ACTIONABLE_ACTIONS or signal.suppressed:
            continue
        if signal.entry is None:
            continue
        future = [candle for candle in ordered if candle.open_time > signal.created_at]
        outcomes.append(
            _label_one(signal, future, max_bars=max_bars, horizons=horizons)
        )
    return outcomes


def _label_one(
    signal: MarketSignal,
    future: list[Candle],
    *,
    max_bars: int,
    horizons: tuple[int, ...],
) -> SignalOutcome:
    action = signal.action.value
    entry = signal.entry or 0.0
    target = signal.take_profit[0] if signal.take_profit else None

    forward_returns = {
        str(horizon): signed_return(action, entry, future[horizon - 1].close)
        for horizon in horizons
        if horizon <= len(future)
    }

    for index, candle in enumerate(future[:max_bars], start=1):
        hit_price, outcome = _exit_within_candle(action, signal.stop_loss, target, candle)
        if hit_price is None:
            continue
        return _resolved(
            signal,
            outcome=outcome,
            resolved_at=candle.close_time or candle.open_time,
            exit_price=hit_price,
            return_pct=signed_return(action, entry, hit_price),
            bars=index,
            forward_returns=forward_returns,
        )

    if len(future) >= max_bars:
        last = future[max_bars - 1]
        return _resolved(
            signal,
            outcome="expired",
            resolved_at=last.close_time or last.open_time,
            exit_price=last.close,
            return_pct=signed_return(action, entry, last.close),
            bars=max_bars,
            forward_returns=forward_returns,
        )

    return _resolved(
        signal,
        outcome="open",
        resolved_at=None,
        exit_price=None,
        return_pct=None,
        bars=None,
        forward_returns=forward_returns,
    )


def _exit_within_candle(
    action: str,
    stop_loss: float | None,
    target: float | None,
    candle: Candle,
) -> tuple[float | None, str]:
    if action == SignalAction.BUY.value:
        if stop_loss is not None and candle.low <= stop_loss:
            return stop_loss, "stop_loss"
        if target is not None and candle.high >= target:
            return target, "take_profit"
    else:
        if stop_loss is not None and candle.high >= stop_loss:
            return stop_loss, "stop_loss"
        if target is not None and candle.low <= target:
            return target, "take_profit"
    return None, ""


def _resolved(
    signal: MarketSignal,
    *,
    outcome: str,
    resolved_at: datetime | None,
    exit_price: float | None,
    return_pct: float | None,
    bars: int | None,
    forward_returns: dict[str, float],
) -> SignalOutcome:
    return SignalOutcome(
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        action=signal.action.value,
        confidence=signal.confidence,
        entry=signal.entry or 0.0,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit[0] if signal.take_profit else None,
        signal_at=signal.created_at,
        outcome=outcome,
        resolved_at=resolved_at,
        exit_price=exit_price,
        return_pct=return_pct,
        bars_to_resolution=bars,
        forward_returns=forward_returns,
    )


@dataclass(slots=True)
class _PendingSignal:
    signal: MarketSignal
    after: datetime
    bars_seen: int = 0


@dataclass(slots=True)
class OutcomeTracker:
    """Resolves live signals into outcomes as new candles arrive."""

    max_bars: int = 96
    _pending: dict[tuple[str, str], list[_PendingSignal]] = field(default_factory=dict)

    def track(self, signal: MarketSignal, *, after: datetime) -> None:
        if signal.action not in ACTIONABLE_ACTIONS or signal.suppressed:
            return
        if signal.entry is None:
            return
        key = (signal.symbol.upper(), signal.timeframe)
        self._pending.setdefault(key, []).append(_PendingSignal(signal=signal, after=after))

    def pending_count(self, symbol: str | None = None) -> int:
        if symbol is None:
            return sum(len(items) for items in self._pending.values())
        return sum(
            len(items)
            for (pending_symbol, _), items in self._pending.items()
            if pending_symbol == symbol.upper()
        )

    def on_candle(self, candle: Candle) -> list[SignalOutcome]:
        key = (candle.symbol.upper(), candle.timeframe)
        pending = self._pending.get(key)
        if not pending:
            return []

        resolved: list[SignalOutcome] = []
        remaining: list[_PendingSignal] = []
        for item in pending:
            if candle.open_time <= item.after:
                remaining.append(item)
                continue
            item.bars_seen += 1
            outcome = self._resolve(item, candle)
            if outcome is None:
                remaining.append(item)
            else:
                resolved.append(outcome)

        if remaining:
            self._pending[key] = remaining
        else:
            del self._pending[key]
        return resolved

    def _resolve(self, item: _PendingSignal, candle: Candle) -> SignalOutcome | None:
        signal = item.signal
        action = signal.action.value
        target = signal.take_profit[0] if signal.take_profit else None
        hit_price, outcome = _exit_within_candle(action, signal.stop_loss, target, candle)
        if hit_price is not None:
            return _resolved(
                signal,
                outcome=outcome,
                resolved_at=candle.close_time or candle.open_time,
                exit_price=hit_price,
                return_pct=signed_return(action, signal.entry or 0.0, hit_price),
                bars=item.bars_seen,
                forward_returns={},
            )
        if item.bars_seen >= self.max_bars:
            return _resolved(
                signal,
                outcome="expired",
                resolved_at=candle.close_time or candle.open_time,
                exit_price=candle.close,
                return_pct=signed_return(action, signal.entry or 0.0, candle.close),
                bars=item.bars_seen,
                forward_returns={},
            )
        return None
