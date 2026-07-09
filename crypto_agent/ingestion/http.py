from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class URLlibAsyncJSONClient:
    """Small default async JSON client; production callers can inject httpx/aiohttp."""

    def __init__(self, *, timeout: float = 10.0, user_agent: str = "crypto-agent-mvp/0.1") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return await asyncio.to_thread(self._get_json_sync, url, params, headers)

    def _get_json_sync(
        self,
        url: str,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
    ) -> Any:
        full_url = _with_query(url, params)
        request_headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if headers:
            request_headers.update(headers)

        request = Request(full_url, headers=request_headers)
        with urlopen(request, timeout=self.timeout) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)


def _with_query(url: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params, doseq=True)}"

