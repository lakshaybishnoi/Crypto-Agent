"""Pure-Python technical indicators used by the signal engine."""

from __future__ import annotations

from math import sqrt

from crypto_agent.core.models import Candle


def simple_moving_average(values: list[float], period: int) -> list[float | None]:
    validate_period(period)
    averages: list[float | None] = []
    running_sum = 0.0
    for index, value in enumerate(values):
        running_sum += value
        if index >= period:
            running_sum -= values[index - period]
        if index + 1 >= period:
            averages.append(running_sum / period)
        else:
            averages.append(None)
    return averages


def ema(values: list[float], period: int) -> list[float | None]:
    validate_period(period)
    if not values:
        return []

    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result

    seed = sum(values[:period]) / period
    result[period - 1] = seed
    multiplier = 2 / (period + 1)
    previous = seed

    for index in range(period, len(values)):
        previous = ((values[index] - previous) * multiplier) + previous
        result[index] = previous
    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    validate_period(period)
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    result[period] = _rsi_from_averages(average_gain, average_loss)

    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = abs(min(change, 0.0))
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        result[index] = _rsi_from_averages(average_gain, average_loss)

    return result


def macd(
    values: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    validate_period(fast_period)
    validate_period(slow_period)
    validate_period(signal_period)
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")

    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    line: list[float | None] = []
    compact_line: list[float] = []
    compact_indexes: list[int] = []

    for index, (fast_value, slow_value) in enumerate(zip(fast, slow, strict=True)):
        if fast_value is None or slow_value is None:
            line.append(None)
            continue
        value = fast_value - slow_value
        line.append(value)
        compact_line.append(value)
        compact_indexes.append(index)

    compact_signal = ema(compact_line, signal_period)
    signal: list[float | None] = [None] * len(values)
    for compact_index, original_index in enumerate(compact_indexes):
        signal[original_index] = compact_signal[compact_index]

    histogram: list[float | None] = []
    for line_value, signal_value in zip(line, signal, strict=True):
        if line_value is None or signal_value is None:
            histogram.append(None)
        else:
            histogram.append(line_value - signal_value)

    return line, signal, histogram


def bollinger_bands(
    values: list[float], period: int = 20, deviations: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    validate_period(period)
    middle = simple_moving_average(values, period)
    upper: list[float | None] = []
    lower: list[float | None] = []

    for index, average in enumerate(middle):
        if average is None:
            upper.append(None)
            lower.append(None)
            continue
        window = values[index - period + 1 : index + 1]
        variance = sum((value - average) ** 2 for value in window) / period
        band_width = sqrt(variance) * deviations
        upper.append(average + band_width)
        lower.append(average - band_width)

    return middle, upper, lower


def true_range(candles: list[Candle]) -> list[float]:
    ranges: list[float] = []
    previous_close: float | None = None

    for candle in candles:
        if previous_close is None:
            ranges.append(candle.high - candle.low)
        else:
            ranges.append(
                max(
                    candle.high - candle.low,
                    abs(candle.high - previous_close),
                    abs(candle.low - previous_close),
                )
            )
        previous_close = candle.close

    return ranges


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    return ema(true_range(candles), period)


def latest_defined(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")


def _rsi_from_averages(average_gain: float, average_loss: float) -> float:
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))
