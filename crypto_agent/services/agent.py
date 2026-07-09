"""Orchestration service for assets, candles, sentiment, and signals."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from crypto_agent.core.models import Asset, Candle, MarketSignal, SignalAction
from crypto_agent.core.stablecoins import is_stablecoin
from crypto_agent.core.timeframes import timeframe_seconds
from crypto_agent.evaluation.outcomes import OutcomeTracker
from crypto_agent.ingestion.coingecko import CoinGeckoClient
from crypto_agent.ingestion.sentiment import SentimentProvider, StaticSentimentProvider
from crypto_agent.paper import PaperEvent, PaperTradingConfig, PaperTradingEngine
from crypto_agent.signals.engine import SignalEngine, SignalEngineConfig
from crypto_agent.storage import PaperTrade as StoredPaperTrade
from crypto_agent.storage import SQLiteStorage

if TYPE_CHECKING:
    from crypto_agent.config import Settings


@dataclass(slots=True)
class AgentService:
    settings: Settings
    asset_provider: CoinGeckoClient
    signal_engine: SignalEngine
    news_provider: SentimentProvider
    social_provider: SentimentProvider
    storage: SQLiteStorage | None = None
    paper_engine: PaperTradingEngine | None = None
    outcome_tracker: OutcomeTracker | None = field(default_factory=OutcomeTracker)
    max_candles_per_symbol: int = 500
    assets: list[Asset] = field(default_factory=list)
    # Candle history is kept per (symbol, timeframe) so indicators never mix bar sizes.
    candles: dict[str, dict[str, deque[Candle]]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    latest_signals: dict[str, MarketSignal] = field(default_factory=dict)

    async def refresh_assets(self) -> list[Asset]:
        self.assets = await self.refresh_top_assets(
            limit=self.settings.top_asset_limit, vs_currency="usd"
        )
        return self.assets

    async def refresh_top_assets(
        self,
        *,
        limit: int | None = None,
        vs_currency: str = "usd",
    ) -> list[Asset]:
        target_limit = limit or self.settings.top_asset_limit
        provider_limit = max(target_limit * 2, target_limit + 10)
        assets = await self.asset_provider.top_market_cap(
            vs_currency=vs_currency, limit=provider_limit
        )
        self.assets = [asset for asset in assets if not is_stablecoin(asset)][:target_limit]
        return self.assets

    def ingest_candle(self, candle: Candle) -> None:
        symbol = candle.symbol.upper()
        series = self._series(symbol, candle.timeframe)
        if series and candle.open_time <= series[-1].open_time:
            if candle.open_time == series[-1].open_time:
                series[-1] = candle
        else:
            series.append(candle)
        while len(series) > self.max_candles_per_symbol:
            series.popleft()
        if self.storage is not None:
            self.storage.candles.save(candle)
        if self.paper_engine is not None:
            event = self.paper_engine.process_candle(candle)
            self._persist_paper_event(event)
        if self.outcome_tracker is not None:
            for outcome in self.outcome_tracker.on_candle(candle):
                if self.storage is not None:
                    self.storage.signal_outcomes.save(outcome)

    async def evaluate_symbol(self, symbol: str, timeframe: str | None = None) -> MarketSignal:
        symbol = symbol.upper()
        timeframe = timeframe or self._default_timeframe(symbol)
        series = self._series(symbol, timeframe) if timeframe else deque()
        news = await self.news_provider.score(symbol)
        social = await self.social_provider.score(symbol)
        signal = self.signal_engine.evaluate(
            symbol,
            list(series),
            news=news,
            social=social,
            timeframe=timeframe,
            higher_timeframe_candles=(
                self._higher_timeframe_series(symbol, timeframe) if timeframe else None
            ),
        )
        self.latest_signals[symbol] = signal
        if self.storage is not None:
            self.storage.sentiment.save(news, symbol=symbol)
            self.storage.sentiment.save(social, symbol=symbol)
            self.storage.signals.save(signal)
        if (
            self.outcome_tracker is not None
            and signal.action in {SignalAction.BUY, SignalAction.SELL}
            and not signal.suppressed
            and series
        ):
            self.outcome_tracker.track(signal, after=series[-1].open_time)
        if self.paper_engine is not None and series:
            event = self.paper_engine.process_signal(signal, series[-1])
            self._persist_paper_event(event)
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

    def paper_snapshot(self):
        if self.paper_engine is None:
            return None
        return self.paper_engine.snapshot()

    def candle_history(self, symbol: str, timeframe: str | None = None) -> list[Candle]:
        timeframe = timeframe or self._default_timeframe(symbol)
        if timeframe is None:
            return []
        return list(self._series(symbol.upper(), timeframe))

    def _series(self, symbol: str, timeframe: str) -> deque[Candle]:
        frames = self.candles[symbol.upper()]
        if timeframe not in frames:
            frames[timeframe] = deque()
        return frames[timeframe]

    def _default_timeframe(self, symbol: str) -> str | None:
        frames = self.candles.get(symbol.upper())
        populated = {tf: series for tf, series in (frames or {}).items() if series}
        if not populated:
            return None
        return max(populated, key=lambda tf: len(populated[tf]))

    def _higher_timeframe_series(self, symbol: str, timeframe: str) -> list[Candle] | None:
        """Next-larger populated timeframe for trend confluence, if one exists."""
        try:
            base_seconds = timeframe_seconds(timeframe)
        except ValueError:
            return None
        frames = self.candles.get(symbol.upper()) or {}
        candidates: list[tuple[int, str]] = []
        for candidate, series in frames.items():
            if len(series) < 21:
                continue
            try:
                seconds = timeframe_seconds(candidate)
            except ValueError:
                continue
            if seconds > base_seconds:
                candidates.append((seconds, candidate))
        if not candidates:
            return None
        _, best = min(candidates)
        return list(frames[best])

    def _persist_paper_event(self, event: PaperEvent | None) -> None:
        if self.storage is None or event is None:
            return
        if event.position is not None and event.action == "opened":
            self.storage.paper_trades.save(
                StoredPaperTrade(
                    symbol=event.position.symbol,
                    side=event.position.side,
                    quantity=event.position.quantity,
                    entry_price=event.position.entry_price,
                    stop_loss=event.position.stop_loss,
                    take_profit=event.position.take_profit,
                    opened_at=event.position.entry_time,
                    fees=event.position.entry_fee,
                    status="open",
                    metadata={"event": event.action, "reason": event.reason},
                )
            )
        if event.trade is not None:
            self.storage.paper_trades.save(
                StoredPaperTrade(
                    symbol=event.trade.symbol,
                    side=event.trade.side,
                    quantity=event.trade.quantity,
                    entry_price=event.trade.entry_price,
                    stop_loss=None,
                    take_profit=[],
                    opened_at=event.trade.entry_time,
                    exit_price=event.trade.exit_price,
                    closed_at=event.trade.exit_time,
                    pnl=event.trade.pnl,
                    fees=event.trade.entry_fee + event.trade.exit_fee,
                    status="closed",
                    metadata={"event": event.action, "reason": event.reason},
                )
            )


def build_agent_service(settings: Settings | None = None) -> AgentService:
    from crypto_agent.config import get_settings
    from crypto_agent.signals.risk import RiskManager

    settings = settings or get_settings()
    target_r = settings.target_r_multiple
    signal_engine = SignalEngine(
        SignalEngineConfig(
            minimum_confidence=settings.minimum_confidence,
            cooldown_seconds=settings.signal_cooldown_seconds,
            regime_filter=settings.regime_filter or None,
        ),
        risk_manager=RiskManager(
            stop_atr_multiplier=settings.stop_atr_multiplier,
            target_multipliers=(target_r, target_r * 2),
        ),
    )
    paper_engine = PaperTradingEngine.with_config(
        PaperTradingConfig(
            initial_cash=settings.paper_starting_balance,
            fee_rate=settings.paper_fee_bps / 10_000,
            slippage_rate=settings.paper_slippage_bps / 10_000,
            position_size_fraction=max(settings.paper_risk_per_trade_pct, 0.0) / 100,
            max_active_trades=settings.paper_max_active_trades,
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
        storage=SQLiteStorage(settings.sqlite_path),
        paper_engine=paper_engine,
    )
