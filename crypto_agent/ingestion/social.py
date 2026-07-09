from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from crypto_agent.core.models import SocialPost
from crypto_agent.core.providers import AsyncJSONClient, SocialProvider


class NullSocialProvider(SocialProvider):
    async def search(self, query: str, *, limit: int = 10) -> Sequence[SocialPost]:
        return ()


class InMemorySocialProvider(SocialProvider):
    def __init__(self, posts: Mapping[str, Sequence[SocialPost]] | None = None) -> None:
        self.posts = dict(posts or {})

    async def search(self, query: str, *, limit: int = 10) -> Sequence[SocialPost]:
        return tuple(self.posts.get(query, ()))[:limit]


class HttpSocialProvider(SocialProvider):
    """Configurable REST adapter for social APIs with injectable transport."""

    def __init__(
        self,
        *,
        http_client: AsyncJSONClient,
        endpoint: str,
        api_key: str | None = None,
        query_param: str = "q",
        limit_param: str = "limit",
        platform: str = "unknown",
    ) -> None:
        self.http_client = http_client
        self.endpoint = endpoint
        self.api_key = api_key
        self.query_param = query_param
        self.limit_param = limit_param
        self.platform = platform

    async def search(self, query: str, *, limit: int = 10) -> Sequence[SocialPost]:
        payload = await self.http_client.get_json(
            self.endpoint,
            params={self.query_param: query, self.limit_param: limit},
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else None,
        )
        return tuple(parse_social_response(payload, default_platform=self.platform))[:limit]


def parse_social_response(payload: Any, *, default_platform: str = "unknown") -> Sequence[SocialPost]:
    if isinstance(payload, Mapping):
        rows = payload.get("posts") or payload.get("items") or payload.get("results") or []
    else:
        rows = payload

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()

    posts: list[SocialPost] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        text = row.get("text") or row.get("body") or row.get("content")
        if not text:
            continue
        posts.append(
            SocialPost(
                text=str(text),
                platform=str(row.get("platform") or default_platform),
                author=_optional_str(row.get("author") or row.get("user") or row.get("username")),
                url=_optional_str(row.get("url") or row.get("link")),
                published_at=_parse_datetime(row.get("publishedAt") or row.get("published_at") or row.get("date")),
                sentiment=_optional_float(row.get("sentiment") or row.get("score")),
                metrics=_parse_metrics(row.get("metrics") or row),
                raw=dict(row),
            )
        )
    return tuple(posts)


def _parse_metrics(value: Any) -> Mapping[str, float]:
    if not isinstance(value, Mapping):
        return {}
    metrics: dict[str, float] = {}
    for key in ("likes", "shares", "comments", "replies", "retweets", "views"):
        try:
            if key in value and value[key] is not None:
                metrics[key] = float(value[key])
        except (TypeError, ValueError):
            continue
    return metrics


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

