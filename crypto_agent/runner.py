"""Long-running worker entrypoint for live signal monitoring."""

from __future__ import annotations

import asyncio
import logging

from crypto_agent.config import get_settings
from crypto_agent.core.models import SignalAction
from crypto_agent.ingestion.binance import BinanceKlineStreamer, BinanceStreamBuilder
from crypto_agent.notifications import TelegramNotifier
from crypto_agent.services.agent import AgentService, build_agent_service

LOGGER = logging.getLogger(__name__)


async def run_live_agent(
    service: AgentService | None = None,
    intervals: list[str] | None = None,
) -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    service = service or build_agent_service(settings)
    intervals = intervals or ["1m", "15m"]

    assets = await service.refresh_assets()
    symbols = [asset.trading_symbol for asset in assets]
    if not symbols:
        raise RuntimeError("No assets available to monitor")

    notifier = _build_notifier()
    streamer = BinanceKlineStreamer(BinanceStreamBuilder(base_url=settings.binance_stream_base_url))

    LOGGER.info("Monitoring %s on intervals %s", ", ".join(symbols), ", ".join(intervals))
    async for candle in streamer.stream(symbols, intervals):
        service.ingest_candle(candle)
        signal = await service.evaluate_symbol(candle.symbol)
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
