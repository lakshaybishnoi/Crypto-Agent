"""Bulk historical candle fetching for evaluation runs."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_agent.core.models import Candle
from crypto_agent.core.timeframes import timeframe_seconds
from crypto_agent.ingestion.historical import BinanceHistoricalClient

_MAX_BATCH = 1_000


def interval_to_seconds(interval: str) -> int:
    return timeframe_seconds(interval)


def candles_for_days(interval: str, days: float) -> int:
    return max(1, int(days * 86_400 / interval_to_seconds(interval)))


async def fetch_history(
    symbol: str,
    interval: str,
    total: int,
    *,
    client: BinanceHistoricalClient | None = None,
    now: datetime | None = None,
) -> list[Candle]:
    """Fetch up to `total` closed candles, paginating backwards from now."""
    client = client or BinanceHistoricalClient()
    now = now or datetime.now(UTC)
    collected: list[Candle] = []
    end_time_ms: int | None = None

    while len(collected) < total:
        limit = min(_MAX_BATCH, total - len(collected) + 1)
        batch = await client.klines(
            symbol, interval=interval, limit=limit, end_time_ms=end_time_ms
        )
        batch = [candle for candle in batch if candle.close_time and candle.close_time <= now]
        if not batch:
            break
        collected = batch + collected
        end_time_ms = int(batch[0].open_time.timestamp() * 1000) - 1
        if len(batch) < limit - 1:
            break

    return collected[-total:]
