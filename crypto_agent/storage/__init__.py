"""Lightweight persistence helpers for local agent state."""

from crypto_agent.storage.sqlite import (
    BacktestResult,
    BacktestResultRepository,
    CandleRepository,
    PaperTrade,
    PaperTradeRepository,
    SentimentSnapshotRepository,
    SignalOutcomeRepository,
    SignalRepository,
    SQLiteStorage,
    connect,
    initialize_schema,
)

__all__ = [
    "BacktestResult",
    "BacktestResultRepository",
    "CandleRepository",
    "PaperTrade",
    "PaperTradeRepository",
    "SentimentSnapshotRepository",
    "SignalOutcomeRepository",
    "SignalRepository",
    "SQLiteStorage",
    "connect",
    "initialize_schema",
]
