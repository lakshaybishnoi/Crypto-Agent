"""In-memory paper trading portfolio with deterministic simulated fills."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from crypto_agent.core.models import Candle, MarketSignal, SignalAction


@dataclass(frozen=True, slots=True)
class PaperTradingConfig:
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    position_size_fraction: float = 0.1
    max_active_trades: int = 3
    allow_short: bool = True


@dataclass(frozen=True, slots=True)
class PaperPosition:
    symbol: str
    side: str
    entry_time: datetime
    entry_price: float
    quantity: float
    entry_fee: float
    margin: float
    stop_loss: float | None = None
    take_profit: list[float] = field(default_factory=list)

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity

    def unrealized_pnl(
        self,
        mark_price: float,
        *,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> float:
        exit_action = "sell" if self.side == "long" else "buy"
        exit_price = _execution_price(mark_price, exit_action, slippage_rate)
        exit_fee = exit_price * self.quantity * fee_rate
        if self.side == "long":
            gross_pnl = (exit_price - self.entry_price) * self.quantity
        else:
            gross_pnl = (self.entry_price - exit_price) * self.quantity
        return gross_pnl - self.entry_fee - exit_fee


@dataclass(frozen=True, slots=True)
class PaperTrade:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    entry_fee: float
    exit_fee: float
    pnl: float
    pnl_pct: float
    exit_reason: str


@dataclass(frozen=True, slots=True)
class PaperEvent:
    action: str
    symbol: str
    reason: str
    position: PaperPosition | None = None
    trade: PaperTrade | None = None


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    active_trades: int
    positions: dict[str, PaperPosition]


@dataclass(slots=True)
class Portfolio:
    config: PaperTradingConfig = field(default_factory=PaperTradingConfig)
    cash: float | None = None
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    closed_trades: list[PaperTrade] = field(default_factory=list)
    last_prices: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash is None:
            self.cash = float(self.config.initial_cash)

    @property
    def active_trades(self) -> int:
        return len(self.positions)

    @property
    def realized_pnl(self) -> float:
        return sum(trade.pnl for trade in self.closed_trades)

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            position.unrealized_pnl(
                self.last_prices.get(symbol, position.entry_price),
                fee_rate=self.config.fee_rate,
                slippage_rate=self.config.slippage_rate,
            )
            for symbol, position in self.positions.items()
        )

    @property
    def equity(self) -> float:
        equity = float(self.cash or 0.0)
        for symbol, position in self.positions.items():
            mark_price = self.last_prices.get(symbol, position.entry_price)
            exit_action = "sell" if position.side == "long" else "buy"
            exit_price = _execution_price(mark_price, exit_action, self.config.slippage_rate)
            exit_notional = exit_price * position.quantity
            exit_fee = exit_notional * self.config.fee_rate
            if position.side == "long":
                equity += exit_notional - exit_fee
            else:
                equity += (
                    position.margin
                    + (position.entry_price - exit_price) * position.quantity
                    - exit_fee
                )
        return equity

    def process_signal(self, signal: MarketSignal, candle: Candle) -> PaperEvent:
        symbol = signal.symbol.upper()
        self.last_prices[symbol] = candle.close

        if signal.suppressed:
            return PaperEvent("ignored", symbol, "signal_suppressed")
        if signal.action not in {SignalAction.BUY, SignalAction.SELL}:
            return PaperEvent("ignored", symbol, f"{signal.action.value}_signal")

        position = self.positions.get(symbol)
        if position is not None:
            if _is_opposite_signal(position, signal.action):
                trade = self.close_position(
                    symbol,
                    candle.close,
                    _execution_time(candle),
                    f"{signal.action.value}_signal",
                )
                return PaperEvent("closed", symbol, f"{signal.action.value}_signal", trade=trade)
            return PaperEvent("ignored", symbol, "duplicate_symbol", position=position)

        return self.open_position(signal, candle)

    def process_candle(self, candle: Candle) -> PaperEvent | None:
        symbol = candle.symbol.upper()
        self.last_prices[symbol] = candle.close
        position = self.positions.get(symbol)
        if position is None:
            return None

        trigger_price, reason = _exit_trigger(position, candle)
        if trigger_price is None:
            return None

        trade = self.close_position(symbol, trigger_price, _execution_time(candle), reason)
        return PaperEvent("closed", symbol, reason, trade=trade)

    def open_position(self, signal: MarketSignal, candle: Candle) -> PaperEvent:
        symbol = signal.symbol.upper()
        if signal.action == SignalAction.SELL and not self.config.allow_short:
            return PaperEvent("rejected", symbol, "shorts_disabled")
        if symbol in self.positions:
            return PaperEvent(
                "rejected",
                symbol,
                "duplicate_symbol",
                position=self.positions[symbol],
            )
        if len(self.positions) >= self.config.max_active_trades:
            return PaperEvent("rejected", symbol, "max_active_trades")

        side = "long" if signal.action == SignalAction.BUY else "short"
        entry_action = "buy" if side == "long" else "sell"
        raw_entry = signal.entry or candle.close
        entry_price = _execution_price(raw_entry, entry_action, self.config.slippage_rate)
        allocation = float(self.cash or 0.0) * self.config.position_size_fraction
        spendable = allocation / (1 + self.config.fee_rate)
        quantity = spendable / entry_price if entry_price else 0.0
        if quantity <= 0:
            return PaperEvent("rejected", symbol, "insufficient_cash")

        notional = quantity * entry_price
        entry_fee = notional * self.config.fee_rate
        if side == "long":
            next_cash = float(self.cash or 0.0) - notional - entry_fee
            margin = 0.0
        else:
            margin = notional
            next_cash = float(self.cash or 0.0) - margin - entry_fee

        if next_cash < -1e-9:
            return PaperEvent("rejected", symbol, "insufficient_cash")

        position = PaperPosition(
            symbol=symbol,
            side=side,
            entry_time=_execution_time(candle),
            entry_price=entry_price,
            quantity=quantity,
            entry_fee=entry_fee,
            margin=margin,
            stop_loss=signal.stop_loss,
            take_profit=list(signal.take_profit),
        )
        self.cash = max(next_cash, 0.0)
        self.positions[symbol] = position
        self.last_prices[symbol] = candle.close
        return PaperEvent("opened", symbol, "signal", position=position)

    def close_position(
        self,
        symbol: str,
        raw_price: float,
        exit_time: datetime,
        exit_reason: str,
    ) -> PaperTrade | None:
        symbol = symbol.upper()
        position = self.positions.pop(symbol, None)
        if position is None:
            return None

        exit_action = "sell" if position.side == "long" else "buy"
        exit_price = _execution_price(raw_price, exit_action, self.config.slippage_rate)
        exit_notional = exit_price * position.quantity
        exit_fee = exit_notional * self.config.fee_rate

        if position.side == "long":
            gross_pnl = (exit_price - position.entry_price) * position.quantity
            self.cash = float(self.cash or 0.0) + exit_notional - exit_fee
            basis = position.notional + position.entry_fee
        else:
            gross_pnl = (position.entry_price - exit_price) * position.quantity
            self.cash = float(self.cash or 0.0) + position.margin + gross_pnl - exit_fee
            basis = position.margin + position.entry_fee

        pnl = gross_pnl - position.entry_fee - exit_fee
        trade = PaperTrade(
            symbol=symbol,
            side=position.side,
            entry_time=position.entry_time,
            exit_time=exit_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            entry_fee=position.entry_fee,
            exit_fee=exit_fee,
            pnl=pnl,
            pnl_pct=pnl / basis if basis else 0.0,
            exit_reason=exit_reason,
        )
        self.closed_trades.append(trade)
        self.last_prices[symbol] = raw_price
        return trade

    def snapshot(self, prices: Mapping[str, float] | None = None) -> PortfolioSnapshot:
        if prices:
            self.last_prices.update({symbol.upper(): price for symbol, price in prices.items()})
        return PortfolioSnapshot(
            cash=float(self.cash or 0.0),
            equity=self.equity,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.unrealized_pnl,
            active_trades=len(self.positions),
            positions=dict(self.positions),
        )


def _execution_price(price: float, action: str, slippage_rate: float) -> float:
    if action == "buy":
        return price * (1 + slippage_rate)
    if action == "sell":
        return price * (1 - slippage_rate)
    raise ValueError(f"Unsupported execution action: {action}")


def _is_opposite_signal(position: PaperPosition, action: SignalAction) -> bool:
    return (
        position.side == "long"
        and action == SignalAction.SELL
        or position.side == "short"
        and action == SignalAction.BUY
    )


def _exit_trigger(position: PaperPosition, candle: Candle) -> tuple[float | None, str]:
    target = position.take_profit[0] if position.take_profit else None
    if position.side == "long":
        if position.stop_loss is not None and candle.low <= position.stop_loss:
            return position.stop_loss, "stop_loss"
        if target is not None and candle.high >= target:
            return target, "take_profit"
    else:
        if position.stop_loss is not None and candle.high >= position.stop_loss:
            return position.stop_loss, "stop_loss"
        if target is not None and candle.low <= target:
            return target, "take_profit"
    return None, ""


def _execution_time(candle: Candle) -> datetime:
    return candle.close_time or candle.open_time
