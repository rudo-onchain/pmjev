"""Risk limits.

Paper execution blocks one model for the rest of the UTC day once that model's
settled PnL reaches ``daily_loss_limit_usd``. ``max_notional_usd`` is still unused.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_notional_usd: float | None
    daily_loss_limit_usd: float
