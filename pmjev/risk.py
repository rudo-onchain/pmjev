"""Portfolio limits and live-trading kill switches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pmjev.store import Store


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_notional_usd: float
    max_trade_usd: float
    daily_loss_limit_usd: float
    consecutive_loss_limit: int = 8
    loss_pause_seconds: int = 3600
    max_drawdown_usd: float = 100.0
    reference_stale_seconds: float = 10.0
    jev_error_window_seconds: int = 1800
    jev_error_rate_limit: float = 0.20


class LiveRiskGuard:
    """Fail closed before every order; a latched failure needs process restart."""

    def __init__(
        self,
        store: Store,
        limits: RiskLimits,
        *,
        stop_file: Path,
        reset_at: float = 0.0,
    ) -> None:
        self._store = store
        self._limits = limits
        self._stop_file = stop_file
        self._reset_at = reset_at
        self._latched_reason: str | None = None

    @property
    def latched_reason(self) -> str | None:
        return self._latched_reason

    def latch(self, reason: str) -> None:
        self._latched_reason = reason

    def block_reason(
        self,
        *,
        now: float,
        requested_notional: float,
        reference_timestamp: float,
    ) -> str | None:
        if self._latched_reason is not None:
            return self._latched_reason
        if self._stop_file.exists():
            return f"kill switch file exists: {self._stop_file}"
        reference_age = now - reference_timestamp
        if reference_age > self._limits.reference_stale_seconds:
            return (
                f"reference feed stale ({reference_age:.1f}s > "
                f"{self._limits.reference_stale_seconds:.1f}s)"
            )
        if requested_notional > self._limits.max_trade_usd:
            return (
                f"trade ${requested_notional:.2f} exceeds per-trade limit "
                f"${self._limits.max_trade_usd:.2f}"
            )
        exposure = self._store.open_notional(mode="live")
        if exposure + requested_notional > self._limits.max_notional_usd:
            return (
                f"portfolio exposure ${exposure + requested_notional:.2f} exceeds "
                f"${self._limits.max_notional_usd:.2f}"
            )

        utc_day = now - (now % 86_400)
        daily_pnl = self._store.realized_pnl(mode="live", since_ts=utc_day)
        if daily_pnl <= -self._limits.daily_loss_limit_usd:
            return (
                f"daily live PnL ${daily_pnl:.2f} reached loss limit "
                f"-${self._limits.daily_loss_limit_usd:.2f}"
            )

        results = self._store.recent_live_results(since_ts=self._reset_at)
        consecutive_losses = 0
        last_loss_at = 0.0
        equity = 0.0
        equity_peak = 0.0
        max_drawdown = 0.0
        for result in results:
            pnl = float(result["pnl"])
            equity += pnl
            equity_peak = max(equity_peak, equity)
            max_drawdown = max(max_drawdown, equity_peak - equity)
            if pnl < 0:
                consecutive_losses += 1
                last_loss_at = float(result["closed_at"] or 0)
            else:
                consecutive_losses = 0
        if max_drawdown >= self._limits.max_drawdown_usd:
            self.latch(
                f"drawdown ${max_drawdown:.2f} reached permanent limit "
                f"${self._limits.max_drawdown_usd:.2f}; set RISK_RESET_AT after review"
            )
            return self._latched_reason
        if (
            consecutive_losses >= self._limits.consecutive_loss_limit
            and now < last_loss_at + self._limits.loss_pause_seconds
        ):
            return (
                f"{consecutive_losses} consecutive losses; paused until "
                f"{last_loss_at + self._limits.loss_pause_seconds:.0f}"
            )

        failures, attempts = self._store.jev_error_rate(
            since_ts=now - self._limits.jev_error_window_seconds
        )
        if attempts and failures / attempts > self._limits.jev_error_rate_limit:
            return (
                f"Jev error rate {failures / attempts:.1%} exceeds "
                f"{self._limits.jev_error_rate_limit:.1%} ({failures}/{attempts})"
            )
        return None
