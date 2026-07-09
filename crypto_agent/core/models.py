"""Shared domain models for market data, sentiment, and signals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    WATCH = "watch"


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    symbol: str
    name: str
    market_cap_rank: int | None = None
    current_price: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None

    @property
    def trading_symbol(self) -> str:
        return f"{self.symbol.upper()}USDT"


@dataclass(frozen=True, slots=True)
class AssetMarket(Asset):
    """Extended market snapshot used by provider adapters."""

    total_volume: float | None = None
    price_change_percentage_1h: float | None = None
    price_change_percentage_24h: float | None = None
    price_change_percentage_7d: float | None = None


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str = "1m"
    close_time: datetime | None = None

    @classmethod
    def from_binance_kline(cls, payload: dict[str, Any]) -> Candle:
        kline = payload["k"]
        return cls(
            symbol=payload["s"],
            open_time=datetime.fromtimestamp(kline["t"] / 1000, tz=UTC),
            close_time=datetime.fromtimestamp(kline["T"] / 1000, tz=UTC),
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            timeframe=kline["i"],
        )


@dataclass(frozen=True, slots=True)
class SentimentSnapshot:
    """Normalized sentiment score in the range -1.0 to 1.0."""

    source: str
    score: float
    confidence: float = 1.0
    headline_count: int = 0
    reason: str = "no sentiment signal"
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def weighted_score(self) -> float:
        return clamp(self.score, -1.0, 1.0) * clamp(self.confidence, 0.0, 1.0)


@dataclass(frozen=True, slots=True)
class NewsItem:
    title: str
    url: str | None = None
    source: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    sentiment: float | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class SocialPost:
    text: str
    platform: str
    author: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    sentiment: float | None = None
    metrics: Mapping[str, float] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class SignalComponent:
    name: str
    score: float
    weight: float
    reason: str

    @property
    def weighted_score(self) -> float:
        return clamp(self.score, -1.0, 1.0) * self.weight


@dataclass(frozen=True, slots=True)
class MarketSignal:
    symbol: str
    action: SignalAction
    confidence: float
    timeframe: str
    entry: float | None
    stop_loss: float | None
    take_profit: list[float]
    reason: str
    risk_level: str
    components: list[SignalComponent] = field(default_factory=list)
    suppressed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "confidence": self.confidence,
            "timeframe": self.timeframe,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "suppressed": self.suppressed,
            "created_at": self.created_at.isoformat(),
            "components": [
                {
                    "name": component.name,
                    "score": component.score,
                    "weight": component.weight,
                    "reason": component.reason,
                }
                for component in self.components
            ],
        }


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
