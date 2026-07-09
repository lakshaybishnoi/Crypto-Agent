# Safety Constraints

The MVP must behave as a signal assistant and research tool unless a later phase explicitly changes that contract.

## Defaults

- Run in `CRYPTO_AGENT_MODE=paper`.
- Keep `SAFETY_DRY_RUN=true`.
- Keep `ALLOW_LIVE_TRADING=false`.
- Keep exchange API keys read-only.
- Keep Telegram disabled until credentials and chat destination are configured.

## Required Gates

Before any signal is sent, application code should enforce:

- `KILL_SWITCH` is not enabled.
- Signal confidence is at or above `SIGNAL_MIN_CONFIDENCE`.
- Symbol is in `CRYPTO_AGENT_SYMBOLS`.
- Alert rate stays below `MAX_SIGNALS_PER_HOUR`.
- Risk sizing stays below `MAX_POSITION_RISK_PCT`.
- Daily risk stays below `MAX_DAILY_LOSS_PCT` when execution simulation exists.

## Notification Rules

Telegram messages should be clear and auditable. Each signal should include:

- symbol and timeframe
- direction or posture
- confidence score
- triggering strategy or reason
- timestamp
- dry-run or paper-mode status
- risk disclaimer or no-trade note

Avoid wording that implies guaranteed return, certainty, or investment advice.

## Live Trading Policy

Do not enable live trading during the MVP. A later phase needs:

- backtest evidence
- forward-test evidence
- paper ledger review
- explicit operator approval
- read/write key separation
- maximum loss guardrails
- emergency shutdown procedure

## Secret Handling

- Never commit `.env`.
- Never paste secrets into issue text, docs, or logs.
- Use read-only keys whenever possible.
- Rotate secrets after accidental disclosure.
- Prefer a secret manager for any deployment beyond a local machine.
