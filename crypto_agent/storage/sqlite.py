"""SQLite-backed repositories built on the Python standard library."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_agent.core.models import (
    Candle,
    MarketSignal,
    SentimentSnapshot,
    SignalAction,
    SignalComponent,
)
from crypto_agent.evaluation.outcomes import SignalOutcome

DEFAULT_SQLITE_PATH = Path("data/crypto_agent.sqlite3")

_CANDLE_COLUMNS = (
    "symbol",
    "timeframe",
    "open_time",
    "close_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
_SIGNAL_COLUMNS = (
    "id",
    "symbol",
    "action",
    "confidence",
    "timeframe",
    "entry",
    "stop_loss",
    "take_profit_json",
    "reason",
    "risk_level",
    "components_json",
    "suppressed",
    "created_at",
)
_SENTIMENT_COLUMNS = (
    "id",
    "symbol",
    "source",
    "score",
    "confidence",
    "headline_count",
    "reason",
    "captured_at",
)
_PAPER_TRADE_COLUMNS = (
    "id",
    "signal_id",
    "symbol",
    "side",
    "quantity",
    "entry_price",
    "stop_loss",
    "take_profit_json",
    "opened_at",
    "exit_price",
    "closed_at",
    "pnl",
    "fees",
    "status",
    "metadata_json",
)
_BACKTEST_COLUMNS = (
    "id",
    "strategy",
    "symbol",
    "timeframe",
    "started_at",
    "ended_at",
    "metrics_json",
    "created_at",
)
_SIGNAL_OUTCOME_COLUMNS = (
    "id",
    "signal_id",
    "symbol",
    "timeframe",
    "action",
    "confidence",
    "entry",
    "stop_loss",
    "take_profit",
    "signal_at",
    "outcome",
    "resolved_at",
    "exit_price",
    "return_pct",
    "bars_to_resolution",
    "forward_returns_json",
)


@dataclass(frozen=True, slots=True)
class PaperTrade:
    """Persistable paper trade record."""

    symbol: str
    side: str
    quantity: float
    entry_price: float
    opened_at: datetime
    status: str = "open"
    id: int | None = None
    signal_id: int | None = None
    stop_loss: float | None = None
    take_profit: list[float] = field(default_factory=list)
    exit_price: float | None = None
    closed_at: datetime | None = None
    pnl: float | None = None
    fees: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Persistable backtest summary with free-form metrics."""

    strategy: str
    symbol: str
    timeframe: str
    started_at: datetime
    ended_at: datetime
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


def connect(path: str | Path = DEFAULT_SQLITE_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with row access and local-friendly pragmas."""

    path_value = str(path)
    if path_value != ":memory:":
        Path(path_value).expanduser().parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path_value, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if path_value != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create persistence tables and indexes if they do not already exist."""

    for statement in _SCHEMA:
        connection.execute(statement)
    connection.commit()


class SQLiteStorage:
    """Owns a SQLite connection and exposes typed repositories."""

    def __init__(self, path: str | Path = DEFAULT_SQLITE_PATH, initialize: bool = True) -> None:
        self.path = path
        self.connection = connect(path)
        self._lock = threading.RLock()
        if initialize:
            with self._lock:
                initialize_schema(self.connection)

        self.candles = CandleRepository(self)
        self.signals = SignalRepository(self)
        self.sentiment = SentimentSnapshotRepository(self)
        self.paper_trades = PaperTradeRepository(self)
        self.backtests = BacktestResultRepository(self)
        self.signal_outcomes = SignalOutcomeRepository(self)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self.connection.execute(sql, tuple(params))
            self.connection.commit()
            return cursor

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        materialized_rows = [tuple(row) for row in rows]
        if not materialized_rows:
            return
        with self._lock:
            self.connection.executemany(sql, materialized_rows)
            self.connection.commit()

    def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute(sql, tuple(params)).fetchone()

    def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.connection.execute(sql, tuple(params)).fetchall())

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> SQLiteStorage:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class CandleRepository:
    """Repository for OHLCV candle history."""

    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    def save(self, candle: Candle) -> None:
        self.save_many([candle])

    def save_many(self, candles: Iterable[Candle]) -> None:
        self._storage.executemany(
            """
            INSERT INTO candles (
                symbol, timeframe, open_time, close_time, open, high, low, close, volume
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timeframe, open_time) DO UPDATE SET
                close_time = excluded.close_time,
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume
            """,
            (_candle_to_row(candle) for candle in candles),
        )

    def get(self, symbol: str, open_time: datetime, timeframe: str = "1m") -> Candle | None:
        row = self._storage.fetch_one(
            f"""
            SELECT {_columns(_CANDLE_COLUMNS)}
            FROM candles
            WHERE symbol = ? AND timeframe = ? AND open_time = ?
            """,
            (symbol.upper(), timeframe, _serialize_datetime(open_time)),
        )
        return _row_to_candle(row) if row else None

    def list(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        where, params = _symbol_timeframe_filter(symbol, timeframe)
        sql = f"SELECT {_columns(_CANDLE_COLUMNS)} FROM candles{where} ORDER BY open_time ASC"
        sql, params = _with_limit(sql, params, limit)
        return [_row_to_candle(row) for row in self._storage.fetch_all(sql, params)]

    def latest(
        self,
        symbol: str,
        timeframe: str | None = None,
        limit: int = 100,
    ) -> list[Candle]:
        where, params = _symbol_timeframe_filter(symbol, timeframe)
        sql = f"SELECT {_columns(_CANDLE_COLUMNS)} FROM candles{where} ORDER BY open_time DESC"
        sql, params = _with_limit(sql, params, limit)
        rows = self._storage.fetch_all(sql, params)
        return [_row_to_candle(row) for row in reversed(rows)]


class SignalRepository:
    """Repository for generated market signals."""

    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    def save(self, signal: MarketSignal) -> int:
        cursor = self._storage.execute(
            """
            INSERT INTO market_signals (
                symbol, action, confidence, timeframe, entry, stop_loss, take_profit_json,
                reason, risk_level, components_json, suppressed, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _signal_to_row(signal),
        )
        return int(cursor.lastrowid)

    def get(self, signal_id: int) -> MarketSignal | None:
        row = self._storage.fetch_one(
            f"SELECT {_columns(_SIGNAL_COLUMNS)} FROM market_signals WHERE id = ?",
            (signal_id,),
        )
        return _row_to_signal(row) if row else None

    def list(
        self,
        symbol: str | None = None,
        action: SignalAction | str | None = None,
        limit: int | None = None,
    ) -> list[MarketSignal]:
        where, params = _signal_filter(symbol, action)
        sql = (
            f"SELECT {_columns(_SIGNAL_COLUMNS)} FROM market_signals{where} ORDER BY created_at ASC"
        )
        sql, params = _with_limit(sql, params, limit)
        return [_row_to_signal(row) for row in self._storage.fetch_all(sql, params)]

    def latest(self, symbol: str | None = None) -> MarketSignal | None:
        where, params = _signal_filter(symbol, None)
        sql = f"""
        SELECT {_columns(_SIGNAL_COLUMNS)}
        FROM market_signals{where}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
        row = self._storage.fetch_one(sql, params)
        return _row_to_signal(row) if row else None


class SentimentSnapshotRepository:
    """Repository for normalized news/social sentiment snapshots."""

    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    def save(self, snapshot: SentimentSnapshot, symbol: str | None = None) -> int:
        cursor = self._storage.execute(
            """
            INSERT INTO sentiment_snapshots (
                symbol, source, score, confidence, headline_count, reason, captured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol.upper() if symbol else None,
                snapshot.source,
                snapshot.score,
                snapshot.confidence,
                snapshot.headline_count,
                snapshot.reason,
                _serialize_datetime(snapshot.captured_at),
            ),
        )
        return int(cursor.lastrowid)

    def list(
        self,
        symbol: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[SentimentSnapshot]:
        where, params = _sentiment_filter(symbol, source)
        sql = (
            f"SELECT {_columns(_SENTIMENT_COLUMNS)} FROM sentiment_snapshots{where} "
            "ORDER BY captured_at ASC"
        )
        sql, params = _with_limit(sql, params, limit)
        return [_row_to_sentiment(row) for row in self._storage.fetch_all(sql, params)]

    def latest(
        self,
        symbol: str | None = None,
        source: str | None = None,
    ) -> SentimentSnapshot | None:
        where, params = _sentiment_filter(symbol, source)
        row = self._storage.fetch_one(
            f"""
            SELECT {_columns(_SENTIMENT_COLUMNS)}
            FROM sentiment_snapshots{where}
            ORDER BY captured_at DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        return _row_to_sentiment(row) if row else None


class PaperTradeRepository:
    """Repository for paper trade lifecycle records."""

    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    def save(self, trade: PaperTrade) -> int:
        row = _paper_trade_to_row(trade)
        if trade.id is None:
            cursor = self._storage.execute(
                """
                INSERT INTO paper_trades (
                    signal_id, symbol, side, quantity, entry_price, stop_loss,
                    take_profit_json, opened_at, exit_price, closed_at, pnl, fees,
                    status, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row[1:],
            )
            return int(cursor.lastrowid)

        self._storage.execute(
            """
            INSERT INTO paper_trades (
                id, signal_id, symbol, side, quantity, entry_price, stop_loss,
                take_profit_json, opened_at, exit_price, closed_at, pnl, fees,
                status, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                signal_id = excluded.signal_id,
                symbol = excluded.symbol,
                side = excluded.side,
                quantity = excluded.quantity,
                entry_price = excluded.entry_price,
                stop_loss = excluded.stop_loss,
                take_profit_json = excluded.take_profit_json,
                opened_at = excluded.opened_at,
                exit_price = excluded.exit_price,
                closed_at = excluded.closed_at,
                pnl = excluded.pnl,
                fees = excluded.fees,
                status = excluded.status,
                metadata_json = excluded.metadata_json
            """,
            row,
        )
        return trade.id

    def get(self, trade_id: int) -> PaperTrade | None:
        row = self._storage.fetch_one(
            f"SELECT {_columns(_PAPER_TRADE_COLUMNS)} FROM paper_trades WHERE id = ?",
            (trade_id,),
        )
        return _row_to_paper_trade(row) if row else None

    def list(self, symbol: str | None = None, status: str | None = None) -> list[PaperTrade]:
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._storage.fetch_all(
            f"SELECT {_columns(_PAPER_TRADE_COLUMNS)} FROM paper_trades{where} "
            "ORDER BY opened_at ASC",
            params,
        )
        return [_row_to_paper_trade(row) for row in rows]


class BacktestResultRepository:
    """Repository for backtest summary metrics."""

    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    def save(self, result: BacktestResult) -> int:
        cursor = self._storage.execute(
            """
            INSERT INTO backtest_results (
                strategy, symbol, timeframe, started_at, ended_at, metrics_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.strategy,
                result.symbol.upper(),
                result.timeframe,
                _serialize_datetime(result.started_at),
                _serialize_datetime(result.ended_at),
                _to_json(result.metrics),
                _serialize_datetime(result.created_at),
            ),
        )
        return int(cursor.lastrowid)

    def latest(
        self,
        symbol: str | None = None,
        strategy: str | None = None,
    ) -> BacktestResult | None:
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if strategy:
            clauses.append("strategy = ?")
            params.append(strategy)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._storage.fetch_one(
            f"""
            SELECT {_columns(_BACKTEST_COLUMNS)}
            FROM backtest_results{where}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            params,
        )
        return _row_to_backtest_result(row) if row else None


class SignalOutcomeRepository:
    """Repository for labeled signal outcomes used to measure accuracy."""

    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    def save(self, outcome: SignalOutcome) -> int:
        cursor = self._storage.execute(
            """
            INSERT INTO signal_outcomes (
                signal_id, symbol, timeframe, action, confidence, entry, stop_loss,
                take_profit, signal_at, outcome, resolved_at, exit_price, return_pct,
                bars_to_resolution, forward_returns_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outcome.signal_id,
                outcome.symbol.upper(),
                outcome.timeframe,
                outcome.action,
                outcome.confidence,
                outcome.entry,
                outcome.stop_loss,
                outcome.take_profit,
                _serialize_datetime(outcome.signal_at),
                outcome.outcome,
                _serialize_datetime(outcome.resolved_at) if outcome.resolved_at else None,
                outcome.exit_price,
                outcome.return_pct,
                outcome.bars_to_resolution,
                _to_json(outcome.forward_returns),
            ),
        )
        return int(cursor.lastrowid)

    def list(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        outcome: str | None = None,
        limit: int | None = None,
    ) -> list[SignalOutcome]:
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(timeframe)
        if outcome:
            clauses.append("outcome = ?")
            params.append(outcome)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT {_columns(_SIGNAL_OUTCOME_COLUMNS)} FROM signal_outcomes{where} "
            "ORDER BY signal_at ASC"
        )
        sql, params = _with_limit(sql, params, limit)
        return [_row_to_signal_outcome(row) for row in self._storage.fetch_all(sql, params)]

    def hit_rate(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate decided outcomes into a win/loss summary."""
        clauses = ["outcome IN ('take_profit', 'stop_loss')"]
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(timeframe)
        row = self._storage.fetch_one(
            f"""
            SELECT
                COUNT(*) AS decided,
                SUM(CASE WHEN outcome = 'take_profit' THEN 1 ELSE 0 END) AS wins,
                AVG(return_pct) AS avg_return_pct
            FROM signal_outcomes
            WHERE {' AND '.join(clauses)}
            """,
            params,
        )
        decided = row["decided"] or 0
        wins = row["wins"] or 0
        return {
            "decided": decided,
            "wins": wins,
            "losses": decided - wins,
            "hit_rate": wins / decided if decided else None,
            "avg_return_pct": row["avg_return_pct"],
        }


def _candle_to_row(candle: Candle) -> tuple[Any, ...]:
    return (
        candle.symbol.upper(),
        candle.timeframe,
        _serialize_datetime(candle.open_time),
        _serialize_datetime(candle.close_time) if candle.close_time else None,
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
    )


def _row_to_candle(row: sqlite3.Row) -> Candle:
    return Candle(
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        open_time=_parse_datetime(row["open_time"]),
        close_time=_parse_datetime(row["close_time"]) if row["close_time"] else None,
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
    )


def _signal_to_row(signal: MarketSignal) -> tuple[Any, ...]:
    return (
        signal.symbol.upper(),
        signal.action.value,
        signal.confidence,
        signal.timeframe,
        signal.entry,
        signal.stop_loss,
        _to_json(signal.take_profit),
        signal.reason,
        signal.risk_level,
        _to_json(
            [
                {
                    "name": component.name,
                    "score": component.score,
                    "weight": component.weight,
                    "reason": component.reason,
                }
                for component in signal.components
            ]
        ),
        int(signal.suppressed),
        _serialize_datetime(signal.created_at),
    )


def _row_to_signal(row: sqlite3.Row) -> MarketSignal:
    components = [
        SignalComponent(
            name=component["name"],
            score=component["score"],
            weight=component["weight"],
            reason=component["reason"],
        )
        for component in _from_json(row["components_json"], [])
    ]
    return MarketSignal(
        symbol=row["symbol"],
        action=SignalAction(row["action"]),
        confidence=row["confidence"],
        timeframe=row["timeframe"],
        entry=row["entry"],
        stop_loss=row["stop_loss"],
        take_profit=list(_from_json(row["take_profit_json"], [])),
        reason=row["reason"],
        risk_level=row["risk_level"],
        components=components,
        suppressed=bool(row["suppressed"]),
        created_at=_parse_datetime(row["created_at"]),
    )


def _row_to_sentiment(row: sqlite3.Row) -> SentimentSnapshot:
    return SentimentSnapshot(
        source=row["source"],
        score=row["score"],
        confidence=row["confidence"],
        headline_count=row["headline_count"],
        reason=row["reason"],
        captured_at=_parse_datetime(row["captured_at"]),
    )


def _paper_trade_to_row(trade: PaperTrade) -> tuple[Any, ...]:
    return (
        trade.id,
        trade.signal_id,
        trade.symbol.upper(),
        trade.side,
        trade.quantity,
        trade.entry_price,
        trade.stop_loss,
        _to_json(trade.take_profit),
        _serialize_datetime(trade.opened_at),
        trade.exit_price,
        _serialize_datetime(trade.closed_at) if trade.closed_at else None,
        trade.pnl,
        trade.fees,
        trade.status,
        _to_json(trade.metadata),
    )


def _row_to_paper_trade(row: sqlite3.Row) -> PaperTrade:
    return PaperTrade(
        id=row["id"],
        signal_id=row["signal_id"],
        symbol=row["symbol"],
        side=row["side"],
        quantity=row["quantity"],
        entry_price=row["entry_price"],
        stop_loss=row["stop_loss"],
        take_profit=list(_from_json(row["take_profit_json"], [])),
        opened_at=_parse_datetime(row["opened_at"]),
        exit_price=row["exit_price"],
        closed_at=_parse_datetime(row["closed_at"]) if row["closed_at"] else None,
        pnl=row["pnl"],
        fees=row["fees"],
        status=row["status"],
        metadata=dict(_from_json(row["metadata_json"], {})),
    )


def _row_to_signal_outcome(row: sqlite3.Row) -> SignalOutcome:
    return SignalOutcome(
        id=row["id"],
        signal_id=row["signal_id"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        action=row["action"],
        confidence=row["confidence"],
        entry=row["entry"],
        stop_loss=row["stop_loss"],
        take_profit=row["take_profit"],
        signal_at=_parse_datetime(row["signal_at"]),
        outcome=row["outcome"],
        resolved_at=_parse_datetime(row["resolved_at"]) if row["resolved_at"] else None,
        exit_price=row["exit_price"],
        return_pct=row["return_pct"],
        bars_to_resolution=row["bars_to_resolution"],
        forward_returns=dict(_from_json(row["forward_returns_json"], {})),
    )


def _row_to_backtest_result(row: sqlite3.Row) -> BacktestResult:
    return BacktestResult(
        id=row["id"],
        strategy=row["strategy"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        started_at=_parse_datetime(row["started_at"]),
        ended_at=_parse_datetime(row["ended_at"]),
        metrics=dict(_from_json(row["metrics_json"], {})),
        created_at=_parse_datetime(row["created_at"]),
    )


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _to_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _from_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    return json.loads(value)


def _columns(columns: tuple[str, ...]) -> str:
    return ", ".join(columns)


def _symbol_timeframe_filter(
    symbol: str | None,
    timeframe: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    if timeframe:
        clauses.append("timeframe = ?")
        params.append(timeframe)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _signal_filter(
    symbol: str | None,
    action: SignalAction | str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    if action:
        clauses.append("action = ?")
        params.append(action.value if isinstance(action, SignalAction) else str(action))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _sentiment_filter(symbol: str | None, source: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    if source:
        clauses.append("source = ?")
        params.append(source)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _with_limit(sql: str, params: list[Any], limit: int | None) -> tuple[str, list[Any]]:
    if limit is None:
        return sql, params
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    return f"{sql} LIMIT ?", [*params, limit]


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS candles (
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        open_time TEXT NOT NULL,
        close_time TEXT,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        PRIMARY KEY (symbol, timeframe, open_time)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_candles_symbol_time
    ON candles(symbol, timeframe, open_time)
    """,
    """
    CREATE TABLE IF NOT EXISTS market_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        confidence REAL NOT NULL,
        timeframe TEXT NOT NULL,
        entry REAL,
        stop_loss REAL,
        take_profit_json TEXT NOT NULL,
        reason TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        components_json TEXT NOT NULL,
        suppressed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_market_signals_symbol_created
    ON market_signals(symbol, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_market_signals_action
    ON market_signals(action)
    """,
    """
    CREATE TABLE IF NOT EXISTS sentiment_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        source TEXT NOT NULL,
        score REAL NOT NULL,
        confidence REAL NOT NULL,
        headline_count INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL,
        captured_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sentiment_symbol_source_time
    ON sentiment_snapshots(symbol, source, captured_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER REFERENCES market_signals(id) ON DELETE SET NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity REAL NOT NULL,
        entry_price REAL NOT NULL,
        stop_loss REAL,
        take_profit_json TEXT NOT NULL,
        opened_at TEXT NOT NULL,
        exit_price REAL,
        closed_at TEXT,
        pnl REAL,
        fees REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'open',
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol_status
    ON paper_trades(symbol, status, opened_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_backtest_results_lookup
    ON backtest_results(strategy, symbol, timeframe, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS signal_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER REFERENCES market_signals(id) ON DELETE SET NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        action TEXT NOT NULL,
        confidence REAL NOT NULL,
        entry REAL NOT NULL,
        stop_loss REAL,
        take_profit REAL,
        signal_at TEXT NOT NULL,
        outcome TEXT NOT NULL,
        resolved_at TEXT,
        exit_price REAL,
        return_pct REAL,
        bars_to_resolution INTEGER,
        forward_returns_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_signal_outcomes_lookup
    ON signal_outcomes(symbol, timeframe, outcome, signal_at)
    """,
)
