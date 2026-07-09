from __future__ import annotations

import asyncio
import unittest

from crypto_agent.ingestion.binance import (
    BinanceStreamBuilder,
    build_stream_name,
    parse_combined_kline,
    parse_ticker_message,
)
from crypto_agent.ingestion.coingecko import CoinGeckoClient


class FakeHTTPClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get_json(self, url, *, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.payload


class ProviderTests(unittest.TestCase):
    def test_coingecko_parser_excludes_stablecoins(self):
        client = CoinGeckoClient()
        payload = [
            {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "market_cap_rank": 1},
            {"id": "tether", "symbol": "usdt", "name": "Tether", "market_cap_rank": 2},
            {"id": "ethereum", "symbol": "eth", "name": "Ethereum", "market_cap_rank": 3},
        ]

        assets = client.parse_top_assets(payload, limit=2)

        self.assertEqual([asset.symbol for asset in assets], ["BTC", "ETH"])

    def test_coingecko_uses_injected_http_client(self):
        http_client = FakeHTTPClient(
            [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "market_cap_rank": 1}]
        )
        client = CoinGeckoClient(
            base_url="https://example.test/api", api_key="demo", http_client=http_client
        )

        assets = asyncio.run(client.top_market_cap(limit=1))

        self.assertEqual([asset.symbol for asset in assets], ["BTC"])
        self.assertEqual(http_client.calls[0]["url"], "https://example.test/api/coins/markets")
        self.assertEqual(http_client.calls[0]["headers"], {"x-cg-demo-api-key": "demo"})
        self.assertEqual(http_client.calls[0]["params"]["vs_currency"], "usd")

    def test_binance_stream_url_contains_symbols_and_intervals(self):
        url = BinanceStreamBuilder().combined_kline_url(["BTCUSDT", "ETHUSDT"], ["1m", "15m"])

        self.assertIn("btcusdt@kline_1m", url)
        self.assertIn("ethusdt@kline_15m", url)

    def test_binance_ticker_stream_helpers_normalize_symbols(self):
        self.assertEqual(build_stream_name("BTC"), "btcusdt@ticker")
        self.assertIn("btcusdt@ticker", BinanceStreamBuilder().ticker_url(["BTC"]))

    def test_parse_combined_kline_ignores_open_candles(self):
        payload = {"data": {"e": "kline", "s": "BTCUSDT", "k": {"x": False}}}

        self.assertIsNone(parse_combined_kline(payload))

    def test_parse_ticker_message_accepts_combined_payload(self):
        ticker = parse_ticker_message(
            {
                "stream": "btcusdt@ticker",
                "data": {
                    "s": "BTCUSDT",
                    "c": "65000.25",
                    "P": "1.5",
                    "v": "123.4",
                    "E": 1710000000000,
                },
            }
        )

        self.assertIsNotNone(ticker)
        self.assertEqual(ticker.symbol, "BTCUSDT")
        self.assertEqual(ticker.price, 65000.25)
        self.assertEqual(ticker.price_change_percent, 1.5)
        self.assertIsNotNone(ticker.event_time)


if __name__ == "__main__":
    unittest.main()
