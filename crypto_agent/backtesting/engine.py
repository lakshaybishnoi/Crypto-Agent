"""Historical replay engine for signal-driven strategy backtests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from math import inf

from crypto_agent.core.models import Candle, SentimentSnapshot, SignalAction
from crypto_agent.signals.engine import SignalEngine


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    position_size_fraction: float = 1.0
    max_active_trades: int = 1
    allow_short: bool = True


@dataclass(frozen=True, slots=True)
class BacktestTrade:
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
class EquityPoint:
    timestamp: datetime
    equity: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    initial_cash: float
    final_equity: float
    cash: float
    total_return: float
    win_rate: float
    max_drawdown: float
    profit_factor: float
    trade_count: int
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]

    @property
    def metrics(self) -> dict[str, float | int]:
        return {
            "total_return": self.total_return,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "profit_factor": self.profit_factor,
            "trade_count": self.trade_count,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "initial_cash": self.initial_cash,
            "final_equity": self.final_equity,
            "cash": self.cash,
            "metrics": self.metrics,
            "trades": [asdict(trade) for trade in self.trades],
            "equity_curve": [asdict(point) for point in self.equity_curve],
        }


@dataclass(slots=True)
class _OpenPosition:
    symbol: str
    side: str
    entry_time: datetime
    entry_price: float
    quantity: float
    entry_fee: float
    margin: float
    stop_loss: float | None = None
    take_profit: list[float] = field(default_factory=list)


@dataclass(slots=True)
class BacktestEngine:
    signal_engine: SignalEngine = field(default_factory=SignalEngine)
    config: BacktestConfig = field(default_factory=BacktestConfig)

    def run(
        self,
        candles: Sequence[Candle],
        *,
        news: SentimentSnapshot | None = None,
        social: SentimentSnapshot | None = None,
    ) -> BacktestResult:
        if not candles:
            return self._empty_result()

        ordered_candles = sorted(candles, key=lambda candle: candle.open_time)
        histories: dict[str, list[Candle]] = {}
        last_candles: dict[str, Candle] = {}
        positions: dict[str, _OpenPosition] = {}
        trades: list[BacktestTrade] = []
        equity_curve: list[EquityPoint] = []
        cash = float(self.config.initial_cash)

        for candle in ordered_candles:
            symbol = candle.symbol.upper()
            histories.setdefault(symbol, []).append(candle)
            last_candles[symbol] = candle

            cash = self._close_on_candle_targets(candle, positions, trades, cash)

            signal = self.signal_engine.evaluate(
                symbol,
                histories[symbol],
                news=news,
                social=social,
                timeframe=candle.timeframe,
                now=candle.close_time or candle.open_time,
            )

            position = positions.get(symbol)
            if position and self._is_opposite_signal(position, signal.action):
                cash = self._close_position(
                    position=position,
                    raw_price=candle.close,
                    exit_time=candle.close_time or candle.open_time,
                    exit_reason=f"{signal.action.value}_signal",
                    cash=cash,
                    trades=trades,
                )
                del positions[symbol]
                position = None

            if position is None and self._can_open(
                signal.action,
                signal.suppressed,
                positions,
                symbol,
            ):
                opened = self._open_position(
                    signal.action,
                    candle,
                    signal.entry,
                    signal.stop_loss,
                    signal.take_profit,
                    cash,
                )
                if opened is not None:
                    position, cash = opened
                    positions[symbol] = position

            equity_curve.append(
                EquityPoint(
                    timestamp=candle.close_time or candle.open_time,
                    equity=self._equity(cash, positions, last_candles),
                )
            )

        for symbol, position in list(positions.items()):
            candle = last_candles[symbol]
            cash = self._close_position(
                position=position,
                raw_price=candle.close,
                exit_time=candle.close_time or candle.open_time,
                exit_reason="end_of_backtest",
                cash=cash,
                trades=trades,
            )
            del positions[symbol]

        final_equity = cash
        if equity_curve:
            equity_curve[-1] = EquityPoint(equity_curve[-1].timestamp, final_equity)

        return self._result(cash, final_equity, trades, equity_curve)

    def replay(
        self,
        candles: Sequence[Candle],
        *,
        news: SentimentSnapshot | None = None,
        social: SentimentSnapshot | None = None,
    ) -> BacktestResult:
        return self.run(candles, news=news, social=social)

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            initial_cash=self.config.initial_cash,
            final_equity=self.config.initial_cash,
            cash=self.config.initial_cash,
            total_return=0.0,
            win_rate=0.0,
            max_drawdown=0.0,
            profit_factor=0.0,
            trade_count=0,
            trades=[],
            equity_curve=[],
        )

    def _result(
        self,
        cash: float,
        final_equity: float,
        trades: list[BacktestTrade],
        equity_curve: list[EquityPoint],
    ) -> BacktestResult:
        gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
        gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
        wins = sum(1 for trade in trades if trade.pnl > 0)

        trade_count = len(trades)
        total_return = (
            (final_equity - self.config.initial_cash) / self.config.initial_cash
            if self.config.initial_cash
            else 0.0
        )
        profit_factor = (
            inf
            if gross_profit and gross_loss == 0
            else (gross_profit / gross_loss if gross_loss else 0.0)
        )

        return BacktestResult(
            initial_cash=self.config.initial_cash,
            final_equity=final_equity,
            cash=cash,
            total_return=total_return,
            win_rate=wins / trade_count if trade_count else 0.0,
            max_drawdown=self._max_drawdown(equity_curve),
            profit_factor=profit_factor,
            trade_count=trade_count,
            trades=trades,
            equity_curve=equity_curve,
        )

    def _open_position(
        self,
        action: SignalAction,
        candle: Candle,
        signal_entry: float | None,
        stop_loss: float | None,
        take_profit: list[float],
        cash: float,
    ) -> tuple[_OpenPosition, float] | None:
        raw_entry = signal_entry or candle.close
        side = "long" if action == SignalAction.BUY else "short"
        entry_price = self._execution_price(raw_entry, "buy" if side == "long" else "sell")
        allocation = cash * self.config.position_size_fraction
        if allocation <= 0:
            return None

        spendable = allocation / (1 + self.config.fee_rate)
        quantity = spendable / entry_price if entry_price else 0.0
        if quantity <= 0:
            return None

        notional = quantity * entry_price
        entry_fee = notional * self.config.fee_rate
        if side == "long":
            next_cash = cash - notional - entry_fee
            margin = 0.0
        else:
            margin = notional
            next_cash = cash - margin - entry_fee

        if next_cash < -1e-9:
            return None

        return (
            _OpenPosition(
                symbol=candle.symbol.upper(),
                side=side,
                entry_time=candle.close_time or candle.open_time,
                entry_price=entry_price,
                quantity=quantity,
                entry_fee=entry_fee,
                margin=margin,
                stop_loss=stop_loss,
                take_profit=list(take_profit),
            ),
            max(next_cash, 0.0),
        )

    def _close_position(
        self,
        position: _OpenPosition,
        raw_price: float,
        exit_time: datetime,
        exit_reason: str,
        cash: float,
        trades: list[BacktestTrade],
    ) -> float:
        exit_action = "sell" if position.side == "long" else "buy"
        exit_price = self._execution_price(raw_price, exit_action)
        exit_notional = exit_price * position.quantity
        exit_fee = exit_notional * self.config.fee_rate

        if position.side == "long":
            gross_pnl = (exit_price - position.entry_price) * position.quantity
            next_cash = cash + exit_notional - exit_fee
            basis = position.entry_price * position.quantity + position.entry_fee
        else:
            gross_pnl = (position.entry_price - exit_price) * position.quantity
            next_cash = cash + position.margin + gross_pnl - exit_fee
            basis = position.margin + position.entry_fee

        pnl = gross_pnl - position.entry_fee - exit_fee
        trades.append(
            BacktestTrade(
                symbol=position.symbol,
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
        )
        return next_cash

    def _close_on_candle_targets(
        self,
        candle: Candle,
        positions: dict[str, _OpenPosition],
        trades: list[BacktestTrade],
        cash: float,
    ) -> float:
        symbol = candle.symbol.upper()
        position = positions.get(symbol)
        if position is None:
            return cash

        target_price, reason = self._exit_trigger(position, candle)
        if target_price is None:
            return cash

        next_cash = self._close_position(
            position=position,
            raw_price=target_price,
            exit_time=candle.close_time or candle.open_time,
            exit_reason=reason,
            cash=cash,
            trades=trades,
        )
        del positions[symbol]
        return next_cash

    def _exit_trigger(self, position: _OpenPosition, candle: Candle) -> tuple[float | None, str]:
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

    def _equity(
        self,
        cash: float,
        positions: dict[str, _OpenPosition],
        last_candles: dict[str, Candle],
    ) -> float:
        equity = cash
        for position in positions.values():
            candle = last_candles.get(position.symbol)
            if candle is None:
                continue
            exit_action = "sell" if position.side == "long" else "buy"
            mark_price = self._execution_price(candle.close, exit_action)
            exit_notional = mark_price * position.quantity
            exit_fee = exit_notional * self.config.fee_rate
            if position.side == "long":
                equity += exit_notional - exit_fee
            else:
                equity += (
                    position.margin
                    + (position.entry_price - mark_price) * position.quantity
                    - exit_fee
                )
        return equity

    def _can_open(
        self,
        action: SignalAction,
        suppressed: bool,
        positions: dict[str, _OpenPosition],
        symbol: str,
    ) -> bool:
        if suppressed or action not in {SignalAction.BUY, SignalAction.SELL}:
            return False
        if action == SignalAction.SELL and not self.config.allow_short:
            return False
        if symbol in positions:
            return False
        return len(positions) < self.config.max_active_trades

    def _is_opposite_signal(self, position: _OpenPosition, action: SignalAction) -> bool:
        return (
            position.side == "long"
            and action == SignalAction.SELL
            or position.side == "short"
            and action == SignalAction.BUY
        )

    def _execution_price(self, price: float, action: str) -> float:
        if action == "buy":
            return price * (1 + self.config.slippage_rate)
        if action == "sell":
            return price * (1 - self.config.slippage_rate)
        raise ValueError(f"Unsupported execution action: {action}")

    @staticmethod
    def _max_drawdown(equity_curve: list[EquityPoint]) -> float:
        peak = 0.0
        max_drawdown = 0.0
        for point in equity_curve:
            peak = max(peak, point.equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - point.equity) / peak)
        return max_drawdown
