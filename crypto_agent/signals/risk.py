"""Risk management helpers for generated trade signals."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_agent.analysis.indicators import atr, latest_defined
from crypto_agent.core.models import Candle, SignalAction


@dataclass(frozen=True, slots=True)
class RiskPlan:
    entry: float
    stop_loss: float
    take_profit: list[float]
    risk_level: str


@dataclass(slots=True)
class RiskManager:
    atr_period: int = 14
    stop_atr_multiplier: float = 1.5
    target_multipliers: tuple[float, float] = (1.5, 3.0)

    def plan(self, action: SignalAction, candles: list[Candle]) -> RiskPlan | None:
        if action not in {SignalAction.BUY, SignalAction.SELL} or not candles:
            return None

        entry = candles[-1].close
        current_atr = latest_defined(atr(candles, self.atr_period))
        if current_atr is None or current_atr <= 0:
            current_atr = max(entry * 0.01, 1e-9)

        stop_distance = current_atr * self.stop_atr_multiplier
        if action == SignalAction.BUY:
            stop_loss = entry - stop_distance
            take_profit = [entry + (stop_distance * multiple) for multiple in self.target_multipliers]
        else:
            stop_loss = entry + stop_distance
            take_profit = [entry - (stop_distance * multiple) for multiple in self.target_multipliers]

        volatility_ratio = current_atr / entry if entry else 1.0
        if volatility_ratio >= 0.05:
            risk_level = "high"
        elif volatility_ratio >= 0.025:
            risk_level = "medium"
        else:
            risk_level = "low"

        return RiskPlan(
            entry=round(entry, 8),
            stop_loss=round(stop_loss, 8),
            take_profit=[round(target, 8) for target in take_profit],
            risk_level=risk_level,
        )
