"""HTTP API for operating the signal agent."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from crypto_agent.backtesting import BacktestConfig, BacktestEngine
from crypto_agent.core.models import Candle, SignalAction
from crypto_agent.ingestion.binance import BinanceStreamBuilder
from crypto_agent.services.agent import AgentService, build_agent_service
from crypto_agent.signals.engine import SignalEngine
from crypto_agent.storage import BacktestResult as StoredBacktestResult

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


class BacktestRequest(BaseModel):
    symbol: str = Field(examples=["BTCUSDT"])
    timeframe: str = "15m"
    candle_limit: int = Field(default=500, ge=50, le=5000)
    initial_cash: float = Field(default=10_000.0, gt=0)
    fee_bps: float = Field(default=10.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    position_size_fraction: float = Field(default=1.0, gt=0, le=1.0)


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
async def list_assets(
    service: Annotated[AgentService, Depends(get_service)],
) -> list[dict[str, object]]:
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
        open_time=candle_in.open_time or datetime.now(UTC),
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


@router.get("/history/candles", tags=["history"])
async def candle_history(
    service: Annotated[AgentService, Depends(get_service)],
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=250, ge=1, le=5000),
) -> list[dict[str, object]]:
    storage = _storage_or_404(service)
    return [_as_payload(candle) for candle in storage.candles.list(symbol, timeframe, limit)]


@router.get("/history/signals", tags=["history"])
async def signal_history(
    service: Annotated[AgentService, Depends(get_service)],
    symbol: str | None = Query(default=None),
    action: Annotated[SignalAction | None, Query()] = None,
    limit: int = Query(default=250, ge=1, le=5000),
) -> list[dict[str, object]]:
    storage = _storage_or_404(service)
    return [signal.as_dict() for signal in storage.signals.list(symbol, action, limit)]


@router.get("/history/sentiment", tags=["history"])
async def sentiment_history(
    service: Annotated[AgentService, Depends(get_service)],
    symbol: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=250, ge=1, le=5000),
) -> list[dict[str, object]]:
    storage = _storage_or_404(service)
    return [_as_payload(snapshot) for snapshot in storage.sentiment.list(symbol, source, limit)]


@router.get("/paper/portfolio", tags=["paper-trading"])
async def paper_portfolio(
    service: Annotated[AgentService, Depends(get_service)],
) -> dict[str, object]:
    snapshot = service.paper_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Paper trading is not configured")
    return _as_payload(snapshot)


@router.get("/paper/trades", tags=["paper-trading"])
async def paper_trade_history(
    service: Annotated[AgentService, Depends(get_service)],
    symbol: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[dict[str, object]]:
    storage = _storage_or_404(service)
    return [_as_payload(trade) for trade in storage.paper_trades.list(symbol=symbol, status=status)]


@router.post("/backtests/run", tags=["backtesting"])
async def run_backtest(
    request: BacktestRequest,
    service: Annotated[AgentService, Depends(get_service)],
) -> dict[str, object]:
    storage = _storage_or_404(service)
    candles = storage.candles.latest(
        request.symbol,
        timeframe=request.timeframe,
        limit=request.candle_limit,
    )
    if len(candles) < 50:
        raise HTTPException(
            status_code=422,
            detail=(
                "Not enough stored candles for a backtest. "
                "Ingest or download more candle history first."
            ),
        )

    engine = BacktestEngine(
        signal_engine=SignalEngine(service.signal_engine.config),
        config=BacktestConfig(
            initial_cash=request.initial_cash,
            fee_rate=request.fee_bps / 10_000,
            slippage_rate=request.slippage_bps / 10_000,
            position_size_fraction=request.position_size_fraction,
        ),
    )
    result = engine.run(candles)
    storage.backtests.save(
        StoredBacktestResult(
            strategy="composite-rule-v1",
            symbol=request.symbol,
            timeframe=request.timeframe,
            started_at=candles[0].open_time,
            ended_at=candles[-1].close_time or candles[-1].open_time,
            metrics=result.metrics,
        )
    )
    return _as_payload(result.as_dict())


@router.get("/backtests/latest", tags=["backtesting"])
async def latest_backtest(
    service: Annotated[AgentService, Depends(get_service)],
    symbol: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
) -> dict[str, object] | None:
    storage = _storage_or_404(service)
    result = storage.backtests.latest(symbol=symbol, strategy=strategy)
    return _as_payload(result) if result is not None else None


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
    if isinstance(value, float) and not isfinite(value):
        return str(value)
    return value


def _storage_or_404(service: AgentService):
    if service.storage is None:
        raise HTTPException(status_code=503, detail="Storage is not configured")
    return service.storage
