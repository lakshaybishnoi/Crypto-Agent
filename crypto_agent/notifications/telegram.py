"""Telegram alert transport."""

from dataclasses import dataclass
from typing import Protocol


class AlertLike(Protocol):
    symbol: str
    action: str
    confidence: float
    timeframe: str
    entry: float | None
    stop_loss: float | None
    take_profit: list[float]
    reason: str
    risk_level: str


@dataclass(slots=True)
class TelegramNotifier:
    """Send formatted crypto signal alerts to a Telegram chat."""

    bot_token: str
    chat_id: str
    timeout_seconds: float = 10.0

    async def send_signal(self, signal: AlertLike) -> None:
        await self.send_message(format_signal_message(signal))

    async def send_message(self, text: str) -> None:
        import httpx

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()


def format_signal_message(signal: AlertLike) -> str:
    targets = ", ".join(_format_price(target) for target in signal.take_profit) or "n/a"
    entry = _format_price(signal.entry) if signal.entry is not None else "market/watch"
    stop = _format_price(signal.stop_loss) if signal.stop_loss is not None else "n/a"
    confidence = round(signal.confidence * 100)

    return "\n".join(
        [
            f"*{signal.symbol} {signal.action.upper()} Signal*",
            f"Confidence: *{confidence}%*",
            f"Timeframe: `{signal.timeframe}`",
            f"Entry: `{entry}`",
            f"Stop: `{stop}`",
            f"Targets: `{targets}`",
            f"Risk: *{signal.risk_level}*",
            "",
            signal.reason,
        ]
    )


def _format_price(value: float) -> str:
    if abs(value) >= 1:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")
