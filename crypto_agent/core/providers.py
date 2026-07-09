from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from crypto_agent.core.models import Asset, NewsItem, SocialPost


class AsyncJSONClient(Protocol):
    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        ...


class MarketDataProvider(Protocol):
    async def top_market_cap(
        self,
        *,
        vs_currency: str = "usd",
        limit: int = 100,
    ) -> Sequence[Asset]:
        ...


class NewsProvider(Protocol):
    async def search(self, query: str, *, limit: int = 10) -> Sequence[NewsItem]:
        ...


class SocialProvider(Protocol):
    async def search(self, query: str, *, limit: int = 10) -> Sequence[SocialPost]:
        ...
