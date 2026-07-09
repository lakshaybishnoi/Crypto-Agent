"""Historical candle download helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from crypto_agent.core.models import Candle
from crypto_agent.ingestion.http import URLlibAsyncJSONClient


@dataclass(slots=True)
class BinanceHistoricalClient:
    """Download closed spot candles from Binance REST klines."""

    base_url: str = "https://api.binance.com/api/v3"
    timeout_seconds: float = 10.0

    async def klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[Candle]:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        }
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        client = URLlibAsyncJSONClient(timeout=self.timeout_seconds)
        payload = await client.get_json(f"{self.base_url.rstrip('/')}/klines", params=params)
        return [parse_binance_kline_row(symbol.upper(), interval, row) for row in payload]


def parse_binance_kline_row(symbol: str, interval: str, row: list[Any]) -> Candle:
    return Candle(
        symbol=symbol.upper(),
        open_time=_from_ms(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_time=_from_ms(row[6]),
        timeframe=interval,
    )


def _from_ms(value: int | float | str) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
