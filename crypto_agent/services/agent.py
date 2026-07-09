"""Orchestration service for assets, candles, sentiment, and signals."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from crypto_agent.core.models import Asset, Candle, MarketSignal
from crypto_agent.core.stablecoins import is_stablecoin
from crypto_agent.ingestion.coingecko import CoinGeckoClient
from crypto_agent.ingestion.sentiment import SentimentProvider, StaticSentimentProvider
from crypto_agent.signals.engine import SignalEngine, SignalEngineConfig

if TYPE_CHECKING:
    from crypto_agent.config import Settings


@dataclass(slots=True)
class AgentService:
    settings: "Settings"
    asset_provider: CoinGeckoClient
    signal_engine: SignalEngine
    news_provider: SentimentProvider
    social_provider: SentimentProvider
    max_candles_per_symbol: int = 500
    assets: list[Asset] = field(default_factory=list)
    candles: dict[str, deque[Candle]] = field(default_factory=lambda: defaultdict(deque))
    latest_signals: dict[str, MarketSignal] = field(default_factory=dict)

    async def refresh_assets(self) -> list[Asset]:
        self.assets = await self.refresh_top_assets(limit=self.settings.top_asset_limit, vs_currency="usd")
        return self.assets

    async def refresh_top_assets(
        self,
        *,
        limit: int | None = None,
        vs_currency: str = "usd",
    ) -> list[Asset]:
        target_limit = limit or self.settings.top_asset_limit
        provider_limit = max(target_limit * 2, target_limit + 10)
        assets = await self.asset_provider.top_market_cap(vs_currency=vs_currency, limit=provider_limit)
        self.assets = [asset for asset in assets if not is_stablecoin(asset)][:target_limit]
        return self.assets

    def ingest_candle(self, candle: Candle) -> None:
        symbol = candle.symbol.upper()
        series = self.candles[symbol]
        series.append(candle)
        while len(series) > self.max_candles_per_symbol:
            series.popleft()

    async def evaluate_symbol(self, symbol: str) -> MarketSignal:
        symbol = symbol.upper()
        news = await self.news_provider.score(symbol)
        social = await self.social_provider.score(symbol)
        signal = self.signal_engine.evaluate(symbol, list(self.candles[symbol]), news=news, social=social)
        self.latest_signals[symbol] = signal
        return signal

    async def evaluate_all(self) -> list[MarketSignal]:
        symbols = [asset.trading_symbol for asset in self.assets] or list(self.candles.keys())
        return list(await asyncio.gather(*(self.evaluate_symbol(symbol) for symbol in symbols)))

    async def evaluate_signals(self, symbols: Sequence[str] | None = None) -> list[MarketSignal]:
        if symbols is None:
            return await self.evaluate_all()
        return list(await asyncio.gather(*(self.evaluate_symbol(symbol) for symbol in symbols)))

    async def refresh_and_evaluate(
        self,
        *,
        limit: int | None = None,
        vs_currency: str = "usd",
    ) -> list[MarketSignal]:
        await self.refresh_top_assets(limit=limit, vs_currency=vs_currency)
        return await self.evaluate_signals()


def build_agent_service(settings: Settings | None = None) -> AgentService:
    from crypto_agent.config import get_settings

    settings = settings or get_settings()
    signal_engine = SignalEngine(
        SignalEngineConfig(
            minimum_confidence=settings.minimum_confidence,
            cooldown_seconds=settings.signal_cooldown_seconds,
        )
    )
    return AgentService(
        settings=settings,
        asset_provider=CoinGeckoClient(
            base_url=settings.coingecko_base_url,
            api_key=settings.coingecko_api_key,
        ),
        signal_engine=signal_engine,
        news_provider=StaticSentimentProvider(source="news"),
        social_provider=StaticSentimentProvider(source="social"),
    )
