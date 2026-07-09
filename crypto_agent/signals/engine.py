"""Composite rule-based signal engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from crypto_agent.analysis.indicators import (
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
    ) -> MarketSignal:
        now = now or datetime.now(timezone.utc)
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

        components = [
            self._technical_component(candles),
            self._volume_component(candles),
            self._sentiment_component("news", news, self.config.news_weight),
            self._sentiment_component("social", social, self.config.social_weight),
        ]
        total_weight = sum(component.weight for component in components)
        raw_score = sum(component.weighted_score for component in components) / total_weight
        confidence = clamp(abs(raw_score), 0.0, 1.0)

        if confidence >= self.config.minimum_confidence:
            action = SignalAction.BUY if raw_score > 0 else SignalAction.SELL
        elif confidence >= self.config.watch_confidence:
            action = SignalAction.WATCH
        else:
            action = SignalAction.HOLD

        risk_plan = self.risk_manager.plan(action, candles)
        suppressed = self._is_suppressed(symbol, action, now)
        if action in {SignalAction.BUY, SignalAction.SELL} and not suppressed:
            self._last_alert_at[(symbol.upper(), action)] = now

        reason = self._build_reason(raw_score, components, suppressed)
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

    def _technical_component(self, candles: list[Candle]) -> SignalComponent:
        closes = [candle.close for candle in candles]
        last_close = closes[-1]

        ema_9 = latest_defined(ema(closes, 9))
        ema_21 = latest_defined(ema(closes, 21))
        ema_50 = latest_defined(ema(closes, 50))
        current_rsi = latest_defined(rsi(closes, 14))
        _, _, histogram = macd(closes)
        current_histogram = latest_defined(histogram)
        _, upper_band, lower_band = bollinger_bands(closes, 20)
        upper = latest_defined(upper_band)
        lower = latest_defined(lower_band)

        score = 0.0
        reasons: list[str] = []

        if ema_9 and ema_21:
            if ema_9 > ema_21:
                score += 0.25
                reasons.append("short EMA above medium EMA")
            else:
                score -= 0.25
                reasons.append("short EMA below medium EMA")

        if ema_50:
            if last_close > ema_50:
                score += 0.2
                reasons.append("price above EMA50")
            else:
                score -= 0.2
                reasons.append("price below EMA50")

        if current_histogram is not None:
            if current_histogram > 0:
                score += 0.2
                reasons.append("MACD histogram positive")
            else:
                score -= 0.2
                reasons.append("MACD histogram negative")

        if current_rsi is not None:
            if 45 <= current_rsi <= 70:
                score += 0.2
                reasons.append("RSI in bullish momentum zone")
            elif 30 <= current_rsi < 45:
                score -= 0.1
                reasons.append("RSI weak but not capitulated")
            elif current_rsi < 30:
                score += 0.1
                reasons.append("RSI oversold rebound watch")
            else:
                score -= 0.2
                reasons.append("RSI overbought")

        if upper and lower:
            if last_close > upper:
                score += 0.1
                reasons.append("price breaking upper Bollinger band")
            elif last_close < lower:
                score -= 0.1
                reasons.append("price losing lower Bollinger band")

        return SignalComponent(
            name="technical",
            score=clamp(score, -1.0, 1.0),
            weight=self.config.technical_weight,
            reason=", ".join(reasons) or "technical data neutral",
        )

    def _volume_component(self, candles: list[Candle]) -> SignalComponent:
        volumes = [candle.volume for candle in candles]
        volume_average = latest_defined(simple_moving_average(volumes, min(20, len(volumes))))
        latest_volume = volumes[-1]
        closes = [candle.close for candle in candles]
        price_change = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] else 0.0

        if not volume_average:
            return SignalComponent("volume", 0.0, self.config.volume_weight, "volume neutral")

        ratio = latest_volume / volume_average
        direction = 1.0 if price_change >= 0 else -1.0
        if ratio >= 2.0:
            score = 0.45 * direction
            reason = "major volume expansion"
        elif ratio >= 1.35:
            score = 0.25 * direction
            reason = "above-average volume"
        elif ratio <= 0.6:
            score = -0.1
            reason = "weak participation"
        else:
            score = 0.0
            reason = "normal volume"

        return SignalComponent("volume", clamp(score, -1.0, 1.0), self.config.volume_weight, reason)

    def _sentiment_component(
        self, name: str, sentiment: SentimentSnapshot | None, weight: float
    ) -> SignalComponent:
        if sentiment is None:
            return SignalComponent(name, 0.0, weight, f"no {name} data")
        return SignalComponent(
            name=name,
            score=sentiment.weighted_score(),
            weight=weight,
            reason=sentiment.reason,
        )

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
        strongest = sorted(components, key=lambda component: abs(component.weighted_score), reverse=True)
        explanations = "; ".join(
            f"{component.name}: {component.reason}" for component in strongest[:3]
        )
        cooldown = " Alert suppressed by cooldown." if suppressed else ""
        return f"Composite view is {direction}. {explanations}.{cooldown}"
