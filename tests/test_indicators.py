from datetime import datetime, timezone

from crypto_agent.analysis.indicators import atr, bollinger_bands, ema, macd, rsi
from crypto_agent.core.models import Candle


def test_ema_seeds_from_sma_then_smooths() -> None:
    values = [1, 2, 3, 4, 5, 6]

    result = ema(values, 3)

    assert result[:2] == [None, None]
    assert result[2] == 2
    assert result[-1] == 5


def test_rsi_reaches_100_when_no_losses() -> None:
    values = list(range(1, 25))

    result = rsi(values, 14)

    assert result[-1] == 100


def test_macd_returns_aligned_series() -> None:
    values = [float(index) for index in range(1, 80)]

    line, signal, histogram = macd(values)

    assert len(line) == len(values)
    assert len(signal) == len(values)
    assert len(histogram) == len(values)
    assert histogram[-1] is not None


def test_bollinger_bands_are_ordered() -> None:
    values = [float(index) for index in range(1, 40)]

    middle, upper, lower = bollinger_bands(values, 20)

    assert lower[-1] < middle[-1] < upper[-1]


def test_atr_uses_candle_ranges() -> None:
    candles = [
        Candle(
            symbol="BTCUSDT",
            open_time=datetime.now(timezone.utc),
            open=100 + index,
            high=103 + index,
            low=99 + index,
            close=101 + index,
            volume=10,
        )
        for index in range(20)
    ]

    result = atr(candles, 14)

    assert result[-1] is not None
    assert result[-1] > 0
