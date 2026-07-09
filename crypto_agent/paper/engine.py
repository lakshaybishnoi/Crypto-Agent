"""Paper trading engine that applies live signals to an in-memory portfolio."""

from __future__ import annotations

from dataclasses import dataclass, field

from crypto_agent.core.models import Candle, MarketSignal
from crypto_agent.paper.portfolio import (
    PaperEvent,
    PaperTradingConfig,
    Portfolio,
    PortfolioSnapshot,
)


@dataclass(slots=True)
class PaperTradingEngine:
    portfolio: Portfolio = field(default_factory=Portfolio)

    @classmethod
    def with_config(cls, config: PaperTradingConfig) -> PaperTradingEngine:
        return cls(portfolio=Portfolio(config=config))

    def process_signal(self, signal: MarketSignal, candle: Candle) -> PaperEvent:
        return self.portfolio.process_signal(signal, candle)

    def process_candle(self, candle: Candle) -> PaperEvent | None:
        return self.portfolio.process_candle(candle)

    def process(self, signal: MarketSignal, candle: Candle) -> PaperEvent:
        candle_event = self.process_candle(candle)
        if candle_event is not None:
            return candle_event
        return self.process_signal(signal, candle)

    def snapshot(self) -> PortfolioSnapshot:
        return self.portfolio.snapshot()
