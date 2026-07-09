"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache

try:
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ModuleNotFoundError:
    BaseSettings = None
    Field = None
    SettingsConfigDict = None


if BaseSettings is not None:

    class Settings(BaseSettings):
        """Runtime configuration for local development and production deployment."""

        model_config = SettingsConfigDict(
            env_file=".env", env_file_encoding="utf-8", extra="ignore"
        )

        app_name: str = "Crypto Signal Agent"
        environment: str = Field(default="local", validation_alias="ENVIRONMENT")
        log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

        quote_asset: str = Field(default="USDT", validation_alias="QUOTE_ASSET")
        top_asset_limit: int = Field(default=5, validation_alias="TOP_ASSET_LIMIT")
        signal_interval_seconds: int = Field(
            default=60, validation_alias="SIGNAL_INTERVAL_SECONDS"
        )
        signal_cooldown_seconds: int = Field(
            default=900, validation_alias="SIGNAL_COOLDOWN_SECONDS"
        )
        minimum_confidence: float = Field(
            default=0.62, validation_alias="MINIMUM_CONFIDENCE"
        )

        coingecko_base_url: str = Field(
            default="https://api.coingecko.com/api/v3", validation_alias="COINGECKO_BASE_URL"
        )
        coingecko_api_key: str | None = Field(
            default=None, validation_alias="COINGECKO_API_KEY"
        )
        binance_stream_base_url: str = Field(
            default="wss://stream.binance.com:9443/stream",
            validation_alias="BINANCE_STREAM_BASE_URL",
        )

        telegram_bot_token: str | None = Field(
            default=None, validation_alias="TELEGRAM_BOT_TOKEN"
        )
        telegram_chat_id: str | None = Field(default=None, validation_alias="TELEGRAM_CHAT_ID")

        database_url: str = Field(
            default="postgresql+asyncpg://crypto:crypto@postgres:5432/crypto_agent",
            validation_alias="DATABASE_URL",
        )
        redis_url: str = Field(default="redis://redis:6379/0", validation_alias="REDIS_URL")
        sqlite_path: str = Field(
            default="./data/crypto_agent.sqlite3", validation_alias="SQLITE_PATH"
        )
        paper_starting_balance: float = Field(
            default=10_000.0, validation_alias="PAPER_STARTING_BALANCE"
        )
        paper_max_active_trades: int = Field(
            default=5, validation_alias="PAPER_MAX_ACTIVE_TRADES"
        )
        paper_risk_per_trade_pct: float = Field(
            default=1.0, validation_alias="MAX_POSITION_RISK_PCT"
        )
        paper_fee_bps: float = Field(default=10.0, validation_alias="PAPER_FEE_BPS")
        paper_slippage_bps: float = Field(default=5.0, validation_alias="PAPER_SLIPPAGE_BPS")

else:

    class Settings:
        """Small fallback used before dependencies are installed."""

        def __init__(self, **overrides: object) -> None:
            self.app_name = str(overrides.get("app_name", "Crypto Signal Agent"))
            self.environment = _setting("ENVIRONMENT", "local", overrides, "environment")
            self.log_level = _setting("LOG_LEVEL", "INFO", overrides, "log_level")
            self.quote_asset = _setting("QUOTE_ASSET", "USDT", overrides, "quote_asset")
            self.top_asset_limit = int(
                _setting("TOP_ASSET_LIMIT", "5", overrides, "top_asset_limit")
            )
            self.signal_interval_seconds = int(
                _setting("SIGNAL_INTERVAL_SECONDS", "60", overrides, "signal_interval_seconds")
            )
            self.signal_cooldown_seconds = int(
                _setting("SIGNAL_COOLDOWN_SECONDS", "900", overrides, "signal_cooldown_seconds")
            )
            self.minimum_confidence = float(
                _setting("MINIMUM_CONFIDENCE", "0.62", overrides, "minimum_confidence")
            )
            self.coingecko_base_url = _setting(
                "COINGECKO_BASE_URL",
                "https://api.coingecko.com/api/v3",
                overrides,
                "coingecko_base_url",
            )
            self.coingecko_api_key = _optional_setting(
                "COINGECKO_API_KEY", overrides, "coingecko_api_key"
            )
            self.binance_stream_base_url = _setting(
                "BINANCE_STREAM_BASE_URL",
                "wss://stream.binance.com:9443/stream",
                overrides,
                "binance_stream_base_url",
            )
            self.telegram_bot_token = _optional_setting(
                "TELEGRAM_BOT_TOKEN", overrides, "telegram_bot_token"
            )
            self.telegram_chat_id = _optional_setting(
                "TELEGRAM_CHAT_ID", overrides, "telegram_chat_id"
            )
            self.database_url = _setting(
                "DATABASE_URL",
                "postgresql+asyncpg://crypto:crypto@postgres:5432/crypto_agent",
                overrides,
                "database_url",
            )
            self.redis_url = _setting(
                "REDIS_URL", "redis://redis:6379/0", overrides, "redis_url"
            )
            self.sqlite_path = _setting(
                "SQLITE_PATH", "./data/crypto_agent.sqlite3", overrides, "sqlite_path"
            )
            self.paper_starting_balance = float(
                _setting("PAPER_STARTING_BALANCE", "10000", overrides, "paper_starting_balance")
            )
            self.paper_max_active_trades = int(
                _setting("PAPER_MAX_ACTIVE_TRADES", "5", overrides, "paper_max_active_trades")
            )
            self.paper_risk_per_trade_pct = float(
                _setting("MAX_POSITION_RISK_PCT", "1.0", overrides, "paper_risk_per_trade_pct")
            )
            self.paper_fee_bps = float(
                _setting("PAPER_FEE_BPS", "10", overrides, "paper_fee_bps")
            )
            self.paper_slippage_bps = float(
                _setting("PAPER_SLIPPAGE_BPS", "5", overrides, "paper_slippage_bps")
            )


def _setting(env_name: str, default: str, overrides: dict[str, object], key: str) -> str:
    if key in overrides:
        return str(overrides[key])
    return os.getenv(env_name, default)


def _optional_setting(env_name: str, overrides: dict[str, object], key: str) -> str | None:
    if key in overrides:
        value = overrides[key]
        return str(value) if value is not None else None
    value = os.getenv(env_name)
    return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
