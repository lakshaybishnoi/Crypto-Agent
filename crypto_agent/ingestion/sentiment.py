"""Sentiment provider abstractions and simple offline implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from crypto_agent.core.models import SentimentSnapshot


class SentimentProvider(Protocol):
    async def score(self, symbol: str) -> SentimentSnapshot: ...


@dataclass(slots=True)
class StaticSentimentProvider:
    """Configurable sentiment provider for local tests and first deployment."""

    source: str
    scores: dict[str, SentimentSnapshot] = field(default_factory=dict)

    async def score(self, symbol: str) -> SentimentSnapshot:
        return self.scores.get(
            symbol.upper(),
            SentimentSnapshot(source=self.source, score=0.0, confidence=0.0, reason="no live feed"),
        )
