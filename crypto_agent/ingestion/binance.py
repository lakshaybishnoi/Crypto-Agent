"""Binance stream helpers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from crypto_agent.core.models import Candle


@dataclass(frozen=True, slots=True)
class BinanceStreamBuilder:
    base_url: str = "wss://stream.binance.com:9443/stream"

    def stream_name(self, symbol: str, channel: str = "ticker") -> str:
        return build_stream_name(symbol, channel=channel)

    def stream_url(self, symbol: str, channel: str = "ticker") -> str:
        return f"{_root_base_url(self.base_url)}/ws/{self.stream_name(symbol, channel)}"

    def combined_kline_url(self, symbols: list[str], intervals: list[str]) -> str:
        streams = [
            f"{symbol.lower()}@kline_{interval}"
            for symbol in symbols
            for interval in intervals
        ]
        return f"{self.base_url}?streams={'/'.join(streams)}"

    def ticker_url(self, symbols: list[str]) -> str:
        return build_combined_stream_url(symbols, channel="ticker", base_url=self.base_url)


@dataclass(frozen=True, slots=True)
class BinanceTicker:
    symbol: str
    price: float | None = None
    price_change_percent: float | None = None
    volume: float | None = None
    quote_volume: float | None = None
    event_time: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(slots=True)
class BinanceKlineStreamer:
    builder: BinanceStreamBuilder

    async def stream(self, symbols: list[str], intervals: list[str]) -> AsyncIterator[Candle]:
        import websockets

        url = self.builder.combined_kline_url(symbols, intervals)
        async with websockets.connect(url) as websocket:
            async for raw_message in websocket:
                candle = parse_combined_kline(raw_message)
                if candle is not None:
                    yield candle


def parse_combined_kline(raw_message: str | bytes | dict) -> Candle | None:
    payload = json.loads(raw_message) if isinstance(raw_message, str | bytes) else raw_message
    data = payload.get("data", payload)
    if data.get("e") != "kline":
        return None
    kline = data.get("k", {})
    if not kline.get("x", False):
        return None
    return Candle.from_binance_kline(data)


def normalize_spot_symbol(symbol: str, quote_asset: str = "usdt") -> str:
    token = symbol.strip().replace("/", "").replace("-", "").replace("_", "").lower()
    quote = quote_asset.strip().lower()
    if token.endswith(quote):
        return token
    return f"{token}{quote}"


def build_stream_name(symbol: str, channel: str = "ticker", quote_asset: str = "usdt") -> str:
    return f"{normalize_spot_symbol(symbol, quote_asset)}@{channel.strip().lower()}"


def build_combined_stream_url(
    symbols: list[str] | tuple[str, ...],
    *,
    channel: str = "ticker",
    base_url: str = "wss://stream.binance.com:9443/stream",
    quote_asset: str = "usdt",
) -> str:
    streams = "/".join(
        build_stream_name(symbol, channel=channel, quote_asset=quote_asset)
        for symbol in symbols
    )
    return f"{_combined_base_url(base_url)}?streams={streams}"


def parse_ticker_message(raw_message: str | bytes | dict[str, Any]) -> BinanceTicker | None:
    payload = json.loads(raw_message) if isinstance(raw_message, str | bytes) else raw_message
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None

    symbol = data.get("s") or data.get("symbol")
    if not symbol:
        return None

    return BinanceTicker(
        symbol=str(symbol).upper(),
        price=_optional_float(data.get("c") or data.get("lastPrice")),
        price_change_percent=_optional_float(data.get("P") or data.get("priceChangePercent")),
        volume=_optional_float(data.get("v") or data.get("volume")),
        quote_volume=_optional_float(data.get("q") or data.get("quoteVolume")),
        event_time=_optional_datetime_ms(data.get("E") or data.get("eventTime")),
        raw=dict(data),
    )


def _combined_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized if normalized.endswith("/stream") else f"{normalized}/stream"


def _root_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized.removesuffix("/stream")


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_datetime_ms(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
