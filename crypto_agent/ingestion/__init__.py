"""Market, news, and social data ingestion boundaries."""

from crypto_agent.ingestion.binance import (
    BinanceKlineStreamer,
    BinanceStreamBuilder,
    BinanceTicker,
    build_combined_stream_url,
    build_stream_name,
    normalize_spot_symbol,
    parse_ticker_message,
)
from crypto_agent.ingestion.coingecko import CoinGeckoClient
from crypto_agent.ingestion.historical import BinanceHistoricalClient
from crypto_agent.ingestion.news import HttpNewsProvider, InMemoryNewsProvider, NullNewsProvider
from crypto_agent.ingestion.sentiment import StaticSentimentProvider
from crypto_agent.ingestion.social import (
    HttpSocialProvider,
    InMemorySocialProvider,
    NullSocialProvider,
)

__all__ = [
    "BinanceKlineStreamer",
    "BinanceStreamBuilder",
    "BinanceTicker",
    "BinanceHistoricalClient",
    "CoinGeckoClient",
    "HttpNewsProvider",
    "HttpSocialProvider",
    "InMemoryNewsProvider",
    "InMemorySocialProvider",
    "NullNewsProvider",
    "NullSocialProvider",
    "StaticSentimentProvider",
    "build_combined_stream_url",
    "build_stream_name",
    "normalize_spot_symbol",
    "parse_ticker_message",
]
