"""Long-running worker entrypoint for live signal monitoring."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from crypto_agent.config import get_settings
from crypto_agent.core.models import SignalAction
from crypto_agent.ingestion.binance import BinanceKlineStreamer, BinanceStreamBuilder
from crypto_agent.ingestion.historical import BinanceHistoricalClient
from crypto_agent.notifications import TelegramNotifier
from crypto_agent.services.agent import AgentService, build_agent_service

LOGGER = logging.getLogger(__name__)


async def backfill_history(
    service: AgentService,
    symbols: list[str],
    intervals: list[str],
    limit: int,
    client: BinanceHistoricalClient | None = None,
) -> None:
    """Warm indicator history so signals are meaningful from the first live candle."""
    client = client or BinanceHistoricalClient()
    now = datetime.now(UTC)
    for symbol in symbols:
        for interval in intervals:
            try:
                candles = await client.klines(symbol, interval=interval, limit=limit)
            except Exception:
                LOGGER.warning("Backfill failed for %s %s", symbol, interval, exc_info=True)
                continue
            closed = [
                candle for candle in candles if candle.close_time and candle.close_time <= now
            ]
            for candle in closed:
                service.ingest_candle(candle)
            LOGGER.info("Backfilled %s closed %s candles for %s", len(closed), interval, symbol)


async def run_live_agent(
    service: AgentService | None = None,
    intervals: list[str] | None = None,
) -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    service = service or build_agent_service(settings)
    intervals = intervals or [
        interval.strip()
        for interval in settings.signal_timeframes.split(",")
        if interval.strip()
    ]

    assets = await service.refresh_assets()
    symbols = [asset.trading_symbol for asset in assets]
    if not symbols:
        raise RuntimeError("No assets available to monitor")

    notifier = _build_notifier()
    streamer = BinanceKlineStreamer(BinanceStreamBuilder(base_url=settings.binance_stream_base_url))

    await backfill_history(service, symbols, intervals, settings.backfill_candles)

    LOGGER.info("Monitoring %s on intervals %s", ", ".join(symbols), ", ".join(intervals))
    async for candle in streamer.stream(symbols, intervals):
        service.ingest_candle(candle)
        signal = await service.evaluate_symbol(candle.symbol, timeframe=candle.timeframe)
        LOGGER.info(
            "%s %s confidence=%.2f suppressed=%s",
            signal.symbol,
            signal.action.value,
            signal.confidence,
            signal.suppressed,
        )
        if (
            notifier is not None
            and signal.action in {SignalAction.BUY, SignalAction.SELL}
            and not signal.suppressed
        ):
            await notifier.send_signal(signal)


def _build_notifier() -> TelegramNotifier | None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return None
    return TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )


def main() -> None:
    asyncio.run(run_live_agent())


if __name__ == "__main__":
    main()
