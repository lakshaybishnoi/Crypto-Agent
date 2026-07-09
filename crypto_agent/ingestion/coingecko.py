"""CoinGecko market-cap provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from crypto_agent.core.models import Asset, AssetMarket
from crypto_agent.core.providers import AsyncJSONClient, MarketDataProvider
from crypto_agent.core.stablecoins import STABLECOIN_SYMBOLS
from crypto_agent.ingestion.http import URLlibAsyncJSONClient


DEFAULT_STABLECOINS = {
    "usdt",
    "usdc",
    "dai",
    "fdusd",
    "tusd",
    "usde",
    "usds",
    "busd",
    "pyusd",
} | set(STABLECOIN_SYMBOLS)


@dataclass(slots=True)
class CoinGeckoClient(MarketDataProvider):
    base_url: str = "https://api.coingecko.com/api/v3"
    api_key: str | None = None
    timeout_seconds: float = 10.0
    http_client: AsyncJSONClient | None = field(default=None, repr=False, compare=False)
    stablecoin_symbols: set[str] = field(default_factory=lambda: set(DEFAULT_STABLECOINS))

    async def top_assets(self, limit: int = 5, quote_currency: str = "usd") -> list[Asset]:
        headers = {"x-cg-demo-api-key": self.api_key} if self.api_key else {}
        params = {
            "vs_currency": quote_currency.lower(),
            "order": "market_cap_desc",
            "per_page": max(25, limit * 2),
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        }
        client = self.http_client or URLlibAsyncJSONClient(timeout=self.timeout_seconds)
        payload = await client.get_json(
            f"{self.base_url.rstrip('/')}/coins/markets",
            params=params,
            headers=headers or None,
        )
        return self.parse_top_assets(payload, limit)

    async def top_market_cap(
        self,
        *,
        vs_currency: str = "usd",
        limit: int = 100,
    ) -> Sequence[Asset]:
        return await self.top_assets(limit=limit, quote_currency=vs_currency)

    def parse_top_assets(self, payload: list[dict[str, Any]], limit: int = 5) -> list[Asset]:
        assets: list[Asset] = []
        for item in payload:
            symbol = str(item.get("symbol", "")).lower()
            if not symbol or symbol in self.stablecoin_symbols:
                continue
            assets.append(
                AssetMarket(
                    id=str(item.get("id", symbol)),
                    symbol=symbol.upper(),
                    name=str(item.get("name", symbol.upper())),
                    market_cap_rank=item.get("market_cap_rank"),
                    current_price=_optional_float(item.get("current_price")),
                    market_cap=_optional_float(item.get("market_cap")),
                    volume_24h=_optional_float(item.get("total_volume")),
                    total_volume=_optional_float(item.get("total_volume")),
                    price_change_percentage_1h=_optional_float(
                        item.get("price_change_percentage_1h_in_currency")
                    ),
                    price_change_percentage_24h=_optional_float(
                        item.get("price_change_percentage_24h_in_currency")
                        if "price_change_percentage_24h_in_currency" in item
                        else item.get("price_change_percentage_24h")
                    ),
                    price_change_percentage_7d=_optional_float(
                        item.get("price_change_percentage_7d_in_currency")
                    ),
                )
            )
            if len(assets) >= limit:
                break
        return assets


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
