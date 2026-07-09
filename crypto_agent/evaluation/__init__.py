"""Signal accuracy evaluation: outcome labeling, replay harness, and reports."""

from crypto_agent.evaluation.harness import (
    EvaluationHarness,
    SymbolEvaluation,
    render_report,
)
from crypto_agent.evaluation.history import candles_for_days, fetch_history
from crypto_agent.evaluation.outcomes import (
    OutcomeTracker,
    SignalOutcome,
    label_outcomes,
    signed_return,
)

__all__ = [
    "EvaluationHarness",
    "OutcomeTracker",
    "SignalOutcome",
    "SymbolEvaluation",
    "candles_for_days",
    "fetch_history",
    "label_outcomes",
    "render_report",
    "signed_return",
]
