from datetime import UTC, datetime

from crypto_agent.ingestion.historical import parse_binance_kline_row


def test_parse_binance_kline_row_maps_core_fields() -> None:
    row = [
        1_700_000_000_000,
        "100.0",
        "110.0",
        "95.0",
        "105.0",
        "12.5",
        1_700_000_899_999,
    ]

    candle = parse_binance_kline_row("btcusdt", "15m", row)

    assert candle.symbol == "BTCUSDT"
    assert candle.timeframe == "15m"
    assert candle.open_time == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert candle.close == 105.0
    assert candle.volume == 12.5
