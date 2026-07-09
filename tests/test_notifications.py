from dataclasses import dataclass

from crypto_agent.notifications.telegram import format_signal_message


@dataclass
class FakeSignal:
    symbol: str = "BTCUSDT"
    action: str = "buy"
    confidence: float = 0.78
    timeframe: str = "15m"
    entry: float | None = 61800.0
    stop_loss: float | None = 60900.0
    take_profit: list[float] = None
    reason: str = "Momentum confirmed by trend and sentiment."
    risk_level: str = "medium"

    def __post_init__(self) -> None:
        if self.take_profit is None:
            self.take_profit = [63200.0, 64000.0]


def test_format_signal_message_contains_key_fields() -> None:
    message = format_signal_message(FakeSignal())

    assert "BTCUSDT BUY Signal" in message
    assert "78%" in message
    assert "15m" in message
    assert "60,900" in message
    assert "Momentum confirmed" in message
