"""Composite rule-based signal engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crypto_agent.analysis.indicators import (
    adx,
    atr,
    bollinger_bands,
    ema,
    latest_defined,
    macd,
    rsi,
    simple_moving_average,
)
from crypto_agent.core.models import (
    Candle,
    MarketSignal,
    SentimentSnapshot,
    SignalAction,
    SignalComponent,
    clamp,
)
from crypto_agent.signals.risk import RiskManager


@dataclass(frozen=True, slots=True)
class SignalEngineConfig:
    minimum_confidence: float = 0.62
    watch_confidence: float = 0.45
    cooldown_seconds: int = 900
    technical_weight: float = 0.40
    volume_weight: float = 0.25
    news_weight: float = 0.20
    social_weight: float = 0.15
    minimum_candles: int = 50
    # ADX regime boundaries: above trend_threshold favors trend-following,
    # below range_threshold favors mean reversion, linear blend in between.
    adx_trend_threshold: float = 25.0
    adx_range_threshold: float = 20.0
    # When set ("trending" or "ranging"), BUY/SELL is only allowed in that regime;
    # signals in other regimes are downgraded to WATCH.
    regime_filter: str | None = None


@dataclass(slots=True)
class SignalEngine:
    config: SignalEngineConfig = field(default_factory=SignalEngineConfig)
    risk_manager: RiskManager = field(default_factory=RiskManager)
    _last_alert_at: dict[tuple[str, SignalAction], datetime] = field(default_factory=dict)

    def evaluate(
        self,
        symbol: str,
        candles: list[Candle],
        news: SentimentSnapshot | None = None,
        social: SentimentSnapshot | None = None,
        timeframe: str | None = None,
        now: datetime | None = None,
        higher_timeframe_candles: list[Candle] | None = None,
    ) -> MarketSignal:
        now = now or datetime.now(UTC)
        timeframe = timeframe or (candles[-1].timeframe if candles else "unknown")

        if len(candles) < self.config.minimum_candles:
            return MarketSignal(
                symbol=symbol,
                action=SignalAction.HOLD,
                confidence=0.0,
                timeframe=timeframe,
                entry=candles[-1].close if candles else None,
                stop_loss=None,
                take_profit=[],
                reason=f"Need at least {self.config.minimum_candles} candles before scoring.",
                risk_level="unknown",
                created_at=now,
            )

        technical, regime = self._technical_component(candles)
        components = [
            technical,
            self._volume_component(candles),
            self._sentiment_component("news", news, self.config.news_weight),
            self._sentiment_component("social", social, self.config.social_weight),
        ]
        # Only components with live data participate, so a missing feed does not
        # dilute confidence toward zero.
        scored = [component for component in components if component.has_data]
        total_weight = sum(component.weight for component in scored)
        raw_score = (
            sum(component.weighted_score for component in scored) / total_weight
            if total_weight > 0
            else 0.0
        )
        confidence = clamp(abs(raw_score), 0.0, 1.0)

        if confidence >= self.config.minimum_confidence:
            action = SignalAction.BUY if raw_score > 0 else SignalAction.SELL
        elif confidence >= self.config.watch_confidence:
            action = SignalAction.WATCH
        else:
            action = SignalAction.HOLD

        veto_note = ""
        if (
            action in {SignalAction.BUY, SignalAction.SELL}
            and self.config.regime_filter
            and regime != self.config.regime_filter
        ):
            veto_note = (
                f" Regime is {regime}, not {self.config.regime_filter}; downgraded to watch."
            )
            action = SignalAction.WATCH

        if action in {SignalAction.BUY, SignalAction.SELL} and higher_timeframe_candles:
            higher_trend = self._timeframe_trend(higher_timeframe_candles)
            wants = 1.0 if action == SignalAction.BUY else -1.0
            if higher_trend is not None and higher_trend * wants < 0:
                higher_label = higher_timeframe_candles[-1].timeframe
                veto_note = (
                    f" Higher-timeframe ({higher_label}) trend disagrees; downgraded to watch."
                )
                action = SignalAction.WATCH

        risk_plan = self.risk_manager.plan(action, candles)
        suppressed = self._is_suppressed(symbol, action, now)
        if action in {SignalAction.BUY, SignalAction.SELL} and not suppressed:
            self._last_alert_at[(symbol.upper(), action)] = now

        reason = self._build_reason(raw_score, components, suppressed) + veto_note
        return MarketSignal(
            symbol=symbol.upper(),
            action=action,
            confidence=round(confidence, 4),
            timeframe=timeframe,
            entry=risk_plan.entry if risk_plan else candles[-1].close,
            stop_loss=risk_plan.stop_loss if risk_plan else None,
            take_profit=risk_plan.take_profit if risk_plan else [],
            reason=reason,
            risk_level=risk_plan.risk_level if risk_plan else "none",
            components=components,
            suppressed=suppressed,
            created_at=now,
        )

    def _technical_component(self, candles: list[Candle]) -> tuple[SignalComponent, str]:
        closes = [candle.close for candle in candles]
        last_close = closes[-1]

        ema_9 = latest_defined(ema(closes, 9))
        ema_21 = latest_defined(ema(closes, 21))
        ema_50 = latest_defined(ema(closes, 50))
        current_rsi = latest_defined(rsi(closes, 14))
        _, _, histogram = macd(closes)
        current_histogram = latest_defined(histogram)
        middle_band, upper_band, _ = bollinger_bands(closes, 20)
        middle = latest_defined(middle_band)
        upper = latest_defined(upper_band)
        current_atr = latest_defined(atr(candles, 14))
        current_adx = latest_defined(adx(candles, 14))

        if current_atr is None or current_atr <= 0:
            current_atr = max(abs(last_close) * 0.01, 1e-9)

        trend_score = self._trend_score(
            last_close, ema_9, ema_21, ema_50, current_histogram, current_atr
        )
        reversion_score = self._reversion_score(last_close, current_rsi, middle, upper)
        trend_weight, regime, regime_note = self._regime_weights(current_adx)
        score = trend_weight * trend_score + (1 - trend_weight) * reversion_score

        reason = f"{regime_note}, trend {trend_score:+.2f}, mean-reversion {reversion_score:+.2f}"
        component = SignalComponent(
            name="technical",
            score=clamp(score, -1.0, 1.0),
            weight=self.config.technical_weight,
            reason=reason,
        )
        return component, regime

    def _trend_score(
        self,
        last_close: float,
        ema_9: float | None,
        ema_21: float | None,
        ema_50: float | None,
        histogram: float | None,
        atr_value: float,
    ) -> float:
        """One graded trend feature: correlated EMA/MACD readings are averaged, not stacked."""
        parts: list[float] = []
        if ema_9 is not None and ema_21 is not None:
            parts.append(_grade((ema_9 - ema_21) / atr_value, 0.5))
        if ema_50 is not None:
            parts.append(_grade((last_close - ema_50) / atr_value, 2.0))
        if histogram is not None:
            parts.append(_grade(histogram / atr_value, 0.25))
        return sum(parts) / len(parts) if parts else 0.0

    def _reversion_score(
        self,
        last_close: float,
        current_rsi: float | None,
        middle: float | None,
        upper: float | None,
    ) -> float:
        """Graded fade-the-extremes feature: positive near range lows, negative near highs."""
        parts: list[float] = []
        if current_rsi is not None:
            parts.append(_grade(50.0 - current_rsi, 20.0))
        if middle is not None and upper is not None and upper > middle:
            band_position = (last_close - middle) / (upper - middle)
            parts.append(_grade(-band_position, 1.0))
        return sum(parts) / len(parts) if parts else 0.0

    def _regime_weights(self, adx_value: float | None) -> tuple[float, str, str]:
        """Blend trend-following vs mean-reversion by trend strength (ADX)."""
        if adx_value is None:
            return 0.65, "unknown", "regime unknown (ADX warming up)"
        low = self.config.adx_range_threshold
        high = self.config.adx_trend_threshold
        if adx_value >= high:
            return 0.9, "trending", f"trending regime (ADX {adx_value:.0f})"
        if adx_value <= low:
            return 0.25, "ranging", f"ranging regime (ADX {adx_value:.0f})"
        blend = 0.25 + (0.9 - 0.25) * (adx_value - low) / (high - low)
        return blend, "transitional", f"transitional regime (ADX {adx_value:.0f})"

    def _timeframe_trend(self, candles: list[Candle]) -> float | None:
        closes = [candle.close for candle in candles]
        ema_9 = latest_defined(ema(closes, 9))
        ema_21 = latest_defined(ema(closes, 21))
        if ema_9 is None or ema_21 is None or ema_9 == ema_21:
            return None
        return 1.0 if ema_9 > ema_21 else -1.0

    def _volume_component(self, candles: list[Candle]) -> SignalComponent:
        volumes = [candle.volume for candle in candles]
        closes = [candle.close for candle in candles]
        volume_average = latest_defined(simple_moving_average(volumes, min(20, len(volumes))))

        if not volume_average:
            return SignalComponent(
                "volume", 0.0, self.config.volume_weight, "volume neutral", has_data=False
            )

        ratio = volumes[-1] / volume_average
        lookback = min(3, len(closes) - 1)
        base = closes[-1 - lookback]
        move = (closes[-1] - base) / base if base else 0.0
        direction = 1.0 if move > 0 else -1.0 if move < 0 else 0.0

        # Quiet tape carries no directional information; it must not push the score.
        if ratio <= 0.6:
            return SignalComponent(
                "volume", 0.0, self.config.volume_weight, "weak participation"
            )

        expansion = clamp(ratio - 1.0, 0.0, 1.0)
        score = expansion * direction
        reason = (
            f"volume x{ratio:.2f} vs 20-bar average confirming {lookback}-bar move"
            if score
            else "normal volume"
        )
        return SignalComponent("volume", clamp(score, -1.0, 1.0), self.config.volume_weight, reason)

    def _sentiment_component(
        self, name: str, sentiment: SentimentSnapshot | None, weight: float
    ) -> SignalComponent:
        if sentiment is None or sentiment.confidence <= 0:
            return SignalComponent(name, 0.0, weight, f"no {name} data", has_data=False)
        return SignalComponent(
            name=name,
            score=sentiment.weighted_score(),
            weight=weight,
            reason=sentiment.reason,
        )

    def reset_alert_state(self) -> None:
        """Clear cooldown history so replays start from a clean slate."""
        self._last_alert_at.clear()

    def _is_suppressed(self, symbol: str, action: SignalAction, now: datetime) -> bool:
        if action not in {SignalAction.BUY, SignalAction.SELL}:
            return False
        previous = self._last_alert_at.get((symbol.upper(), action))
        if previous is None:
            return False
        return now - previous < timedelta(seconds=self.config.cooldown_seconds)

    def _build_reason(
        self, raw_score: float, components: list[SignalComponent], suppressed: bool
    ) -> str:
        direction = "bullish" if raw_score > 0 else "bearish" if raw_score < 0 else "neutral"
        strongest = sorted(
            components, key=lambda component: abs(component.weighted_score), reverse=True
        )
        explanations = "; ".join(
            f"{component.name}: {component.reason}" for component in strongest[:3]
        )
        cooldown = " Alert suppressed by cooldown." if suppressed else ""
        return f"Composite view is {direction}. {explanations}.{cooldown}"


def _grade(value: float, full_scale: float) -> float:
    """Scale a raw reading so `full_scale` maps to 1.0, clamped to [-1, 1]."""
    return clamp(value / full_scale, -1.0, 1.0)
