"""HTTP API for operating the signal agent."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from crypto_agent.core.models import Candle
from crypto_agent.ingestion.binance import BinanceStreamBuilder
from crypto_agent.services.agent import AgentService, build_agent_service

router = APIRouter()
_service = build_agent_service()


class CandleIn(BaseModel):
    symbol: str = Field(examples=["BTCUSDT"])
    open_time: datetime | None = None
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str = "1m"


class StreamRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    intervals: list[str] = Field(default_factory=lambda: ["1m", "15m"])


def get_service() -> AgentService:
    return _service


@router.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {
        "name": "Crypto Signal Agent",
        "status": "running",
        "mode": "decision-support",
    }


@router.post("/assets/refresh", tags=["assets"])
async def refresh_assets(
    service: Annotated[AgentService, Depends(get_service)],
    limit: int | None = Query(default=None, ge=1, le=100),
) -> list[dict[str, object]]:
    assets = await service.refresh_top_assets(limit=limit)
    return [_as_payload(asset) for asset in assets]


@router.get("/assets", tags=["assets"])
async def list_assets(service: Annotated[AgentService, Depends(get_service)]) -> list[dict[str, object]]:
    return [_as_payload(asset) for asset in service.assets]


@router.get("/assets/top", tags=["assets"])
async def top_assets(
    service: Annotated[AgentService, Depends(get_service)],
    limit: int = Query(default=25, ge=1, le=100),
) -> list[dict[str, object]]:
    assets = await service.refresh_top_assets(limit=limit)
    return [_as_payload(asset) for asset in assets]


@router.post("/candles", tags=["market-data"])
async def ingest_candle(
    candle_in: CandleIn,
    service: Annotated[AgentService, Depends(get_service)],
) -> dict[str, object]:
    candle = Candle(
        symbol=candle_in.symbol.upper(),
        open_time=candle_in.open_time or datetime.now(timezone.utc),
        open=candle_in.open,
        high=candle_in.high,
        low=candle_in.low,
        close=candle_in.close,
        volume=candle_in.volume,
        timeframe=candle_in.timeframe,
    )
    service.ingest_candle(candle)
    return {"status": "accepted", "symbol": candle.symbol}


@router.post("/signals/evaluate", tags=["signals"])
async def evaluate_signals(
    service: Annotated[AgentService, Depends(get_service)],
) -> list[dict[str, object]]:
    return [signal.as_dict() for signal in await service.evaluate_signals()]


@router.post("/signals/refresh", tags=["signals"])
async def refresh_and_evaluate(
    service: Annotated[AgentService, Depends(get_service)],
    limit: int = Query(default=25, ge=1, le=100),
) -> list[dict[str, object]]:
    return [signal.as_dict() for signal in await service.refresh_and_evaluate(limit=limit)]


@router.post("/signals/{symbol}", tags=["signals"])
async def evaluate_signal(
    symbol: str,
    service: Annotated[AgentService, Depends(get_service)],
) -> dict[str, object]:
    return (await service.evaluate_symbol(symbol)).as_dict()


@router.get("/signals", tags=["signals"])
async def latest_signals(
    service: Annotated[AgentService, Depends(get_service)],
) -> dict[str, dict[str, object]]:
    return {symbol: signal.as_dict() for symbol, signal in service.latest_signals.items()}


@router.post("/streams/binance", tags=["market-data"])
async def build_binance_stream(request: StreamRequest) -> dict[str, str]:
    builder = BinanceStreamBuilder()
    return {"url": builder.combined_kline_url(request.symbols, request.intervals)}


def _as_payload(value):
    if is_dataclass(value):
        return _as_payload(asdict(value))
    if isinstance(value, dict):
        return {key: _as_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_payload(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
