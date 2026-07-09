from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from crypto_agent.core.models import Asset, Candle, SentimentSnapshot, SignalAction
from crypto_agent.services.agent import AgentService
from crypto_agent.signals.engine import SignalEngine, SignalEngineConfig


class FakeSettings:
    top_asset_limit = 2


class FakeMarketProvider:
    def __init__(self, assets):
        self.assets = assets
        self.calls = []

    async def top_market_cap(self, *, vs_currency="usd", limit=100):
        self.calls.append({"vs_currency": vs_currency, "limit": limit})
        return self.assets[:limit]


class FakeSentimentProvider:
    def __init__(self, source: str, score: float):
        self.source = source
        self.score_value = score

    async def score(self, symbol: str) -> SentimentSnapshot:
        return SentimentSnapshot(
            source=self.source,
            score=self.score_value,
            confidence=1.0,
            reason=f"{self.source} fixture for {symbol}",
        )


def make_service(provider: FakeMarketProvider) -> AgentService:
    return AgentService(
        settings=FakeSettings(),
        asset_provider=provider,
        signal_engine=SignalEngine(
            SignalEngineConfig(
                minimum_confidence=0.20,
                watch_confidence=0.10,
                cooldown_seconds=0,
                minimum_candles=50,
            )
        ),
        news_provider=FakeSentimentProvider("news", 0.8),
        social_provider=FakeSentimentProvider("social", 0.5),
    )


def make_trending_candles(symbol: str, count: int = 60) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []
    for index in range(count):
        price = 100.0 + index
        candles.append(
            Candle(
                symbol=symbol,
                open_time=start + timedelta(minutes=index),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price + 0.5,
                volume=1_000 + (index * 20),
                timeframe="1m",
            )
        )
    return candles


class AgentServiceTests(unittest.TestCase):
    def test_refresh_top_assets_filters_stablecoins(self):
        provider = FakeMarketProvider(
            [
                Asset(id="tether", symbol="USDT", name="Tether", market_cap_rank=3),
                Asset(id="bitcoin", symbol="BTC", name="Bitcoin", market_cap_rank=1),
                Asset(id="ethereum", symbol="ETH", name="Ethereum", market_cap_rank=2),
            ]
        )
        service = make_service(provider)

        assets = asyncio.run(service.refresh_top_assets(limit=2))

        self.assertEqual([asset.symbol for asset in assets], ["BTC", "ETH"])
        self.assertEqual(provider.calls, [{"vs_currency": "usd", "limit": 12}])

    def test_refresh_and_evaluate_scores_signals_for_refreshed_assets(self):
        provider = FakeMarketProvider(
            [Asset(id="bitcoin", symbol="BTC", name="Bitcoin", market_cap_rank=1)]
        )
        service = make_service(provider)
        for candle in make_trending_candles("BTCUSDT"):
            service.ingest_candle(candle)

        signals = asyncio.run(service.refresh_and_evaluate(limit=1))

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].symbol, "BTCUSDT")
        self.assertEqual(signals[0].action, SignalAction.BUY)
        self.assertIn("BTCUSDT", service.latest_signals)

    def test_candle_timeframes_are_kept_separate(self):
        provider = FakeMarketProvider([])
        service = make_service(provider)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(60):
            service.ingest_candle(
                Candle(
                    symbol="BTCUSDT",
                    open_time=start + timedelta(minutes=index),
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=1_000,
                    timeframe="1m",
                )
            )
        for index in range(10):
            service.ingest_candle(
                Candle(
                    symbol="BTCUSDT",
                    open_time=start + timedelta(minutes=15 * index),
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=1_000,
                    timeframe="15m",
                )
            )

        self.assertEqual(len(service.candle_history("BTCUSDT", "1m")), 60)
        self.assertEqual(len(service.candle_history("BTCUSDT", "15m")), 10)
        self.assertTrue(
            all(candle.timeframe == "1m" for candle in service.candle_history("BTCUSDT", "1m"))
        )

        signal_15m = asyncio.run(service.evaluate_symbol("BTCUSDT", timeframe="15m"))
        self.assertEqual(signal_15m.timeframe, "15m")
        # 15m only has 10 candles, so the engine must refuse to score it.
        self.assertEqual(signal_15m.action, SignalAction.HOLD)
        self.assertIn("Need at least", signal_15m.reason)

        default_signal = asyncio.run(service.evaluate_symbol("BTCUSDT"))
        self.assertEqual(default_signal.timeframe, "1m")

    def test_higher_timeframe_veto_applies_through_service(self):
        provider = FakeMarketProvider([])
        service = make_service(provider)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        price = 100.0
        for index in range(80):
            price += 1.2
            service.ingest_candle(
                Candle(
                    symbol="BTCUSDT",
                    open_time=start + timedelta(minutes=index),
                    open=price - 0.8,
                    high=price + 1.5,
                    low=price - 1.2,
                    close=price,
                    volume=1_000 + index * 20,
                    timeframe="1m",
                )
            )
        bearish = 500.0
        for index in range(30):
            bearish -= 2.0
            service.ingest_candle(
                Candle(
                    symbol="BTCUSDT",
                    open_time=start + timedelta(minutes=15 * index),
                    open=bearish + 1.0,
                    high=bearish + 2.0,
                    low=bearish - 2.0,
                    close=bearish,
                    volume=500,
                    timeframe="15m",
                )
            )

        signal = asyncio.run(service.evaluate_symbol("BTCUSDT", timeframe="1m"))

        self.assertEqual(signal.action, SignalAction.WATCH)
        self.assertIn("Higher-timeframe", signal.reason)

    def test_duplicate_candles_replace_instead_of_append(self):
        provider = FakeMarketProvider([])
        service = make_service(provider)
        open_time = datetime(2026, 1, 1, tzinfo=UTC)
        first = Candle(
            symbol="BTCUSDT",
            open_time=open_time,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1_000,
            timeframe="1m",
        )
        revised = Candle(
            symbol="BTCUSDT",
            open_time=open_time,
            open=100,
            high=102,
            low=99,
            close=101,
            volume=1_500,
            timeframe="1m",
        )

        service.ingest_candle(first)
        service.ingest_candle(revised)

        history = service.candle_history("BTCUSDT", "1m")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].close, 101)


if __name__ == "__main__":
    unittest.main()
