from datetime import UTC, datetime

from crypto_agent.analysis.indicators import adx, atr, bollinger_bands, ema, macd, rsi
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


def _candle(index: int, close: float, high: float, low: float) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        open_time=datetime.now(UTC),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=10,
    )


def test_adx_is_high_in_a_steady_trend_and_low_in_chop() -> None:
    trending = [
        _candle(index, 100 + index, 101 + index, 99 + index) for index in range(60)
    ]
    choppy = [
        _candle(index, 100 + (index % 2), 101 + (index % 2), 99 + (index % 2))
        for index in range(60)
    ]

    trend_adx = adx(trending, 14)[-1]
    chop_adx = adx(choppy, 14)[-1]

    assert trend_adx is not None and chop_adx is not None
    assert trend_adx > 50
    assert chop_adx < trend_adx
    assert chop_adx < 40


def test_adx_returns_none_until_enough_candles() -> None:
    candles = [_candle(index, 100 + index, 101 + index, 99 + index) for index in range(20)]

    result = adx(candles, 14)

    assert result[-1] is None
    assert len(result) == 20


def test_atr_uses_candle_ranges() -> None:
    candles = [
        Candle(
            symbol="BTCUSDT",
            open_time=datetime.now(UTC),
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
