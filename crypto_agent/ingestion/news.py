from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from crypto_agent.core.models import NewsItem
from crypto_agent.core.providers import AsyncJSONClient, NewsProvider


class NullNewsProvider(NewsProvider):
    async def search(self, query: str, *, limit: int = 10) -> Sequence[NewsItem]:
        return ()


class InMemoryNewsProvider(NewsProvider):
    def __init__(self, items: Mapping[str, Sequence[NewsItem]] | None = None) -> None:
        self.items = dict(items or {})

    async def search(self, query: str, *, limit: int = 10) -> Sequence[NewsItem]:
        return tuple(self.items.get(query, ()))[:limit]


class HttpNewsProvider(NewsProvider):
    """Configurable REST adapter for news APIs with injectable transport."""

    def __init__(
        self,
        *,
        http_client: AsyncJSONClient,
        endpoint: str,
        api_key: str | None = None,
        query_param: str = "q",
        limit_param: str = "limit",
    ) -> None:
        self.http_client = http_client
        self.endpoint = endpoint
        self.api_key = api_key
        self.query_param = query_param
        self.limit_param = limit_param

    async def search(self, query: str, *, limit: int = 10) -> Sequence[NewsItem]:
        payload = await self.http_client.get_json(
            self.endpoint,
            params={self.query_param: query, self.limit_param: limit},
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else None,
        )
        return tuple(parse_news_response(payload))[:limit]


def parse_news_response(payload: Any) -> Sequence[NewsItem]:
    if isinstance(payload, Mapping):
        rows = payload.get("articles") or payload.get("items") or payload.get("results") or []
    else:
        rows = payload

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()

    items: list[NewsItem] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        title = row.get("title") or row.get("headline") or row.get("name")
        if not title:
            continue
        source = row.get("source")
        if isinstance(source, Mapping):
            source = source.get("name")
        items.append(
            NewsItem(
                title=str(title),
                url=_optional_str(row.get("url") or row.get("link")),
                source=_optional_str(source),
                published_at=_parse_datetime(
                    row.get("publishedAt") or row.get("published_at") or row.get("date")
                ),
                summary=_optional_str(
                    row.get("description") or row.get("summary") or row.get("content")
                ),
                sentiment=_optional_float(row.get("sentiment") or row.get("score")),
                raw=dict(row),
            )
        )
    return tuple(items)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
