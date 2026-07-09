"""Daily report builder for Telegram-sized operator summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any


@dataclass(frozen=True, slots=True)
class TradeSummary:
    """Normalized trade row that can be rendered in a daily report."""

    symbol: str
    side: str
    status: str = "closed"
    quantity: float | None = None
    entry: float | None = None
    exit: float | None = None
    pnl: float | None = None
    fees: float | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PnLSummary:
    """Daily profit and loss values for a paper or backtest ledger."""

    realized: float = 0.0
    unrealized: float = 0.0
    fees: float = 0.0
    currency: str = "USD"
    starting_equity: float | None = None
    ending_equity: float | None = None
    open_positions: int = 0

    @property
    def net(self) -> float:
        return self.realized + self.unrealized - self.fees


@dataclass(frozen=True, slots=True)
class DailyReport:
    """Inputs required to render the operator-facing daily report."""

    report_date: date = field(default_factory=lambda: datetime.now(UTC).date())
    signals: Sequence[Any] = ()
    trades: Sequence[Any] = ()
    pnl: Any | None = None
    notes: Sequence[str] = ()
    timezone_label: str = "UTC"


@dataclass(frozen=True, slots=True)
class DailyReportBuilder:
    """Build concise Markdown text for Telegram daily summaries."""

    max_signals: int = 8
    max_trades: int = 8
    max_notes: int = 3
    max_chars: int = 3900

    def build(self, report: DailyReport | Mapping[str, Any]) -> str:
        report = _coerce_report(report)
        signals = list(report.signals)
        trades = list(report.trades)
        pnl = _coerce_pnl(report.pnl, trades)

        lines = [
            f"*Daily Crypto Report - {report.report_date.isoformat()}*",
            f"Window: {report.timezone_label}",
            "",
            "*Summary*",
            _format_signal_summary(signals),
            _format_trade_summary(trades),
            _format_pnl_summary(pnl),
        ]
        equity_line = _format_equity_summary(pnl)
        if equity_line:
            lines.append(equity_line)

        if signals:
            lines.extend(["", "*Top Signals*"])
            for index, signal in enumerate(signals[: self.max_signals], start=1):
                lines.append(_format_signal_line(index, signal))
                reason = _clean_text(_value(signal, "reason", "notes", default=""))
                if reason:
                    lines.append(f"  {_escape_markdown(reason)}")
            remaining = len(signals) - self.max_signals
            if remaining > 0:
                lines.append(f"...and {remaining} more signals")

        if trades:
            lines.extend(["", "*Trades*"])
            for index, trade in enumerate(trades[: self.max_trades], start=1):
                lines.append(_format_trade_line(index, trade, pnl.currency))
                reason = _clean_text(_value(trade, "reason", "notes", default=""))
                if reason:
                    lines.append(f"  {_escape_markdown(reason)}")
            remaining = len(trades) - self.max_trades
            if remaining > 0:
                lines.append(f"...and {remaining} more trades")

        if report.notes:
            lines.extend(["", "*Notes*"])
            for note in report.notes[: self.max_notes]:
                cleaned = _clean_text(note, max_len=220)
                if cleaned:
                    lines.append(f"- {_escape_markdown(cleaned)}")
            remaining = len(report.notes) - self.max_notes
            if remaining > 0:
                lines.append(f"...and {remaining} more notes")

        return _fit_telegram_message("\n".join(lines), self.max_chars)


def build_daily_report(
    *,
    report_date: date | None = None,
    signals: Sequence[Any] = (),
    trades: Sequence[Any] = (),
    pnl: Any | None = None,
    notes: Sequence[str] = (),
    timezone_label: str = "UTC",
    builder: DailyReportBuilder | None = None,
) -> str:
    """Convenience wrapper for callers that do not need to hold a builder."""

    report = DailyReport(
        report_date=report_date or datetime.now(UTC).date(),
        signals=signals,
        trades=trades,
        pnl=pnl,
        notes=notes,
        timezone_label=timezone_label,
    )
    return (builder or DailyReportBuilder()).build(report)


def _coerce_report(report: DailyReport | Mapping[str, Any]) -> DailyReport:
    if isinstance(report, DailyReport):
        return report
    return DailyReport(
        report_date=_coerce_date(report.get("report_date")) or datetime.now(UTC).date(),
        signals=tuple(report.get("signals", ())),
        trades=tuple(report.get("trades", ())),
        pnl=report.get("pnl"),
        notes=tuple(report.get("notes", ())),
        timezone_label=str(report.get("timezone_label", "UTC")),
    )


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _coerce_pnl(pnl: Any | None, trades: Sequence[Any]) -> PnLSummary:
    if isinstance(pnl, PnLSummary):
        return pnl

    if pnl is None:
        realized = sum(
            _number_or_zero(_value(trade, "pnl", "realized_pnl"))
            for trade in trades
            if _is_closed_trade(trade)
        )
        unrealized = sum(
            _number_or_zero(_value(trade, "pnl", "unrealized_pnl"))
            for trade in trades
            if _is_open_trade(trade)
        )
        fees = sum(_trade_fees(trade) for trade in trades)
        return PnLSummary(
            realized=realized,
            unrealized=unrealized,
            fees=fees,
            open_positions=sum(1 for trade in trades if _is_open_trade(trade)),
        )

    open_positions = _number(_value(pnl, "open_positions", "active_positions"))
    return PnLSummary(
        realized=_number_or_zero(_value(pnl, "realized", "realized_pnl", "closed_pnl")),
        unrealized=_number_or_zero(_value(pnl, "unrealized", "unrealized_pnl", "open_pnl")),
        fees=_number_or_zero(_value(pnl, "fees", "fee_total")),
        currency=_clean_text(_value(pnl, "currency", default="USD"), max_len=12).upper() or "USD",
        starting_equity=_number(_value(pnl, "starting_equity", "starting_balance")),
        ending_equity=_number(_value(pnl, "ending_equity", "ending_balance")),
        open_positions=int(open_positions)
        if open_positions is not None
        else sum(1 for trade in trades if _is_open_trade(trade)),
    )


def _format_signal_summary(signals: Sequence[Any]) -> str:
    if not signals:
        return "Signals: 0 total; no signal activity"

    actions = Counter(_signal_action(signal) for signal in signals)
    action_parts = [
        f"{action} {actions[action]}"
        for action in ("BUY", "SELL", "WATCH", "HOLD")
        if actions[action] > 0
    ]
    action_parts.extend(
        f"{action} {count}"
        for action, count in sorted(actions.items())
        if action not in {"BUY", "SELL", "WATCH", "HOLD"}
    )
    actionable = sum(
        1
        for signal in signals
        if _signal_action(signal) in {"BUY", "SELL"} and not _is_suppressed_signal(signal)
    )
    suppressed = sum(1 for signal in signals if _is_suppressed_signal(signal))
    return (
        f"Signals: {len(signals)} total ({' / '.join(action_parts)}); "
        f"{actionable} actionable, {suppressed} suppressed"
    )


def _format_trade_summary(trades: Sequence[Any]) -> str:
    if not trades:
        return "Trades: 0 recorded"

    closed = [trade for trade in trades if _is_closed_trade(trade)]
    open_count = sum(1 for trade in trades if _is_open_trade(trade))
    pnl_values = [_number(_value(trade, "pnl", "realized_pnl")) for trade in closed]
    completed = [value for value in pnl_values if value is not None]
    if completed:
        wins = sum(1 for value in completed if value > 0)
        win_rate = round(wins / len(completed) * 100)
        return (
            f"Trades: {len(trades)} recorded; {len(closed)} closed, {open_count} open; "
            f"win rate {win_rate}% ({wins}/{len(completed)})"
        )
    return f"Trades: {len(trades)} recorded; {len(closed)} closed, {open_count} open"


def _format_pnl_summary(pnl: PnLSummary) -> str:
    return (
        f"PnL: realized {_money(pnl.realized, pnl.currency)}, "
        f"unrealized {_money(pnl.unrealized, pnl.currency)}, "
        f"fees {_money(pnl.fees, pnl.currency, signed=False)}, "
        f"net {_money(pnl.net, pnl.currency)}"
    )


def _format_equity_summary(pnl: PnLSummary) -> str | None:
    if pnl.starting_equity is None or pnl.ending_equity is None:
        return None
    change_pct = _percent_change(pnl.starting_equity, pnl.ending_equity)
    pct = f" ({change_pct:+.2f}%)" if change_pct is not None else ""
    return (
        f"Equity: {_money(pnl.starting_equity, pnl.currency, signed=False)} -> "
        f"{_money(pnl.ending_equity, pnl.currency, signed=False)}{pct}"
    )


def _format_signal_line(index: int, signal: Any) -> str:
    symbol = _escape_markdown(_clean_text(_value(signal, "symbol", default="UNKNOWN")).upper())
    action = _escape_markdown(_signal_action(signal))
    confidence = _format_confidence(_value(signal, "confidence", default=0.0))
    timeframe = _escape_markdown(_clean_text(_value(signal, "timeframe", default="n/a")))
    entry = _price_or_na(_value(signal, "entry", "entry_price"))
    stop = _price_or_na(_value(signal, "stop_loss", "stop"))
    targets = _format_targets(_value(signal, "take_profit", "targets", default=()))
    risk = _escape_markdown(_clean_text(_value(signal, "risk_level", "risk", default="n/a")))
    suppressed = " | suppressed" if _is_suppressed_signal(signal) else ""
    return (
        f"{index}. {symbol} {action} {confidence} {timeframe} | entry {entry} | "
        f"stop {stop} | targets {targets} | risk {risk}{suppressed}"
    )


def _format_trade_line(index: int, trade: Any, currency: str) -> str:
    symbol = _escape_markdown(_clean_text(_value(trade, "symbol", default="UNKNOWN")).upper())
    side = _escape_markdown(_clean_text(_value(trade, "side", "action", default="trade")).upper())
    status = _escape_markdown(_trade_status(trade))
    quantity = _quantity_or_na(_value(trade, "quantity", "qty", "size"))
    entry = _price_or_na(_value(trade, "entry", "entry_price"))
    exit_price = _price_or_na(_value(trade, "exit", "exit_price"))
    pnl = _number(_value(trade, "pnl", "realized_pnl"))
    pnl_text = _money(pnl, currency) if pnl is not None else "n/a"
    return (
        f"{index}. {symbol} {side} {status} | qty {quantity} | entry {entry} | "
        f"exit {exit_price} | PnL {pnl_text}"
    )


def _signal_action(signal: Any) -> str:
    action = _value(signal, "action", "side", default="hold")
    return _clean_text(action).upper()


def _is_suppressed_signal(signal: Any) -> bool:
    return bool(_value(signal, "suppressed", default=False))


def _is_closed_trade(trade: Any) -> bool:
    status = _clean_text(_value(trade, "status", default="")).lower()
    if status in {"closed", "filled", "exited", "stopped", "completed"}:
        return True
    if status in {"open", "active", "pending"}:
        return False
    return _value(trade, "exit", "exit_price") is not None


def _is_open_trade(trade: Any) -> bool:
    status = _clean_text(_value(trade, "status", default="")).lower()
    if status in {"open", "active", "pending"}:
        return True
    if status in {"closed", "filled", "exited", "stopped", "completed"}:
        return False
    return _value(trade, "exit", "exit_price") is None


def _trade_status(trade: Any) -> str:
    status = _clean_text(_value(trade, "status", default="")).lower()
    if status:
        return status
    return "closed" if _is_closed_trade(trade) else "open"


def _trade_fees(trade: Any) -> float:
    fee_total = _number(_value(trade, "fees", "fee"))
    if fee_total is not None:
        return fee_total
    return _number_or_zero(_value(trade, "entry_fee")) + _number_or_zero(
        _value(trade, "exit_fee")
    )


def _format_confidence(value: Any) -> str:
    confidence = _number(value, default=0.0) or 0.0
    if confidence <= 1:
        confidence *= 100
    return f"{round(confidence)}%"


def _format_targets(value: Any) -> str:
    targets: list[str] = []
    if isinstance(value, str):
        candidates: Sequence[Any] = tuple(part.strip() for part in value.split(","))
    elif isinstance(value, Sequence):
        candidates = value
    else:
        candidates = (value,)

    for candidate in candidates:
        number = _number(candidate)
        if number is not None:
            targets.append(_format_price(number))
    return ", ".join(targets) if targets else "n/a"


def _price_or_na(value: Any) -> str:
    number = _number(value)
    return _format_price(number) if number is not None else "n/a"


def _quantity_or_na(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    return f"{number:,.8f}".rstrip("0").rstrip(".") or "0"


def _format_price(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 1:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".") or "0"


def _money(value: float | None, currency: str, *, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    sign = ""
    if signed and value > 0:
        sign = "+"
    elif signed and value < 0:
        sign = "-"

    prefix = "$" if currency.upper() == "USD" else f"{currency.upper()} "
    return f"{sign}{prefix}{abs(value):,.2f}"


def _percent_change(start: float, end: float) -> float | None:
    if start == 0:
        return None
    return (end - start) / start * 100


def _value(item: Any, *names: str, default: Any = None) -> Any:
    if item is None:
        return default
    if isinstance(item, Mapping):
        for name in names:
            value = item.get(name)
            if value is not None:
                return value
        return default

    for name in names:
        value = getattr(item, name, None)
        if value is not None:
            return value
    return default


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
        if not value:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _number_or_zero(value: Any) -> float:
    return _number(value, default=0.0) or 0.0


def _clean_text(value: Any, *, max_len: int = 180) -> str:
    if isinstance(value, Enum):
        text = str(value.value)
    else:
        text = str(value)
    text = " ".join(text.strip().split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for char in ("`", "*", "_", "[", "]"):
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def _fit_telegram_message(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    suffix = "\n\n...truncated for Telegram..."
    allowed = max_chars - len(suffix)
    if allowed <= 0:
        return suffix.strip()[:max_chars]

    trimmed = text[:allowed]
    if "\n" in trimmed:
        trimmed = trimmed.rsplit("\n", 1)[0]
    return trimmed.rstrip() + suffix
