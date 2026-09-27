"""Paper, shadow, and tightly gated live execution."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pmjev.market.live import LiveOrderGateway
from pmjev.risk import LiveRiskGuard
from pmjev.store import EntryAttempt, StoreBackend, TradeRecord

logger = logging.getLogger(__name__)

Side = Literal["up", "down"]
TradeAction = Literal["buy_up", "buy_down", "skip"]
Levels = Sequence[tuple[float, float]]


def fee_per_share(price: float, fee_rate: float, exponent: int = 1) -> float:
    """Return the Polymarket taker fee for one share.

    Gamma currently publishes ``feeSchedule.rate`` and ``feeSchedule.exponent``.
    With the verified crypto schedule (rate 0.07, exponent 1), this is the public
    formula ``rate * (price * (1-price))``.
    """

    if not 0 <= price <= 1:
        raise ValueError("price must be between zero and one")
    if fee_rate < 0:
        raise ValueError("fee_rate cannot be negative")
    if exponent < 1:
        raise ValueError("fee exponent must be positive")
    return fee_rate * (price * (1.0 - price)) ** exponent


def simulated_pnl(*, side: Side, price: float, size: float, fee: float, outcome: int) -> float:
    won = (side == "up" and outcome == 1) or (side == "down" and outcome == 0)
    payout = size if won else 0.0
    return payout - price * size - fee


TICK = 0.01


@dataclass(frozen=True, slots=True)
class Candidate:
    """One model's trading view at a checkpoint.

    ``probability_up`` is the probability used for edge and exits (after any market
    anchoring). ``raw_probability_up`` is the model's own output, used for the
    model-market gap guard. ``rule_based`` candidates (the naive_spot control) skip
    the edge and gap checks; they keep every feed, spot, and loss guard.
    """

    model: str
    probability_up: float
    requested_side: Side | None = None
    raw_probability_up: float | None = None
    rule_based: bool = False
    # Rule-based candidates cross the book only up to this price.
    max_price: float | None = None


def anchor_to_market(probability_up: float, market_mid: float | None, k: float) -> float:
    """Shrink a model probability toward the market midpoint: mid + k * (p - mid)."""

    if not 0.0 <= k <= 1.0:
        raise ValueError("shrink k must be between zero and one")
    if market_mid is None or k == 1.0:
        return probability_up
    return min(1.0, max(0.0, market_mid + k * (probability_up - market_mid)))


@dataclass(frozen=True, slots=True)
class EntryPlan:
    side: Side
    price: float
    size: float
    fee: float
    max_price: float = 0.99


@dataclass(frozen=True, slots=True)
class EntryDecision:
    plan: EntryPlan | None
    reason: str
    side: Side | None = None
    fresh_ask: float | None = None
    max_price: float | None = None
    depth_to_max_usd: float | None = None


@dataclass(frozen=True, slots=True)
class AttemptContext:
    """Timing and decision-time quotes used to log how the fresh book differed."""

    snapshot_up_ask: float | None
    snapshot_down_ask: float | None
    snapshot_ts: float
    decided_at: float


def utc_day_start(now: float) -> float:
    """Return the UTC midnight timestamp that starts the day containing ``now``."""

    moment = datetime.fromtimestamp(now, tz=UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class Executor:
    def __init__(
        self,
        mode: str,
        store: StoreBackend,
        fee_peak: float,
        daily_loss_limit_usd: float = 25.0,
        live_gateway: LiveOrderGateway | None = None,
        live_risk: LiveRiskGuard | None = None,
        live_min_shares: float = 5.0,
        paper_early_exits: bool = True,
        paper_slippage_ticks: int = 0,
    ) -> None:
        if paper_slippage_ticks < 0:
            raise ValueError("paper_slippage_ticks cannot be negative")
        self._mode = mode
        self._store = store
        self._fee_peak = fee_peak
        self._daily_loss_limit_usd = daily_loss_limit_usd
        self._live_gateway = live_gateway
        self._live_risk = live_risk
        self._live_min_shares = live_min_shares
        self._paper_early_exits = paper_early_exits
        self._slippage = paper_slippage_ticks * TICK
        self._live_lock = asyncio.Lock()

    def evaluate_exit(
        self,
        *,
        slug: str,
        prediction_id: int,
        candidate: Candidate,
        up_bid: float | None,
        down_bid: float | None,
        fee_rate: float | None = None,
        fee_exponent: int = 1,
        spot: float | None = None,
        price_to_beat: float | None = None,
    ) -> TradeRecord | None:
        """Close an existing paper trade when its model no longer clears the exit bid."""

        if self._mode != "paper" or not self._paper_early_exits or candidate.rule_based:
            return None
        row = self._store.trade_for_exit(slug, candidate.model, prediction_id)
        if row is None:
            return None
        side: Side = "up" if str(row["side"]) == "up" else "down"
        bid = up_bid if side == "up" else down_bid
        if bid is None or bid <= 0:
            logger.info(
                "paper exit held: missing bid model=%s slug=%s side=%s",
                candidate.model,
                slug,
                side,
            )
            return None
        bid = max(TICK, bid - self._slippage)
        effective_rate = fee_rate if fee_rate is not None else self._fee_peak * 4.0
        exit_fee_per_share = fee_per_share(bid, effective_rate, fee_exponent)
        held_probability = (
            candidate.probability_up if side == "up" else 1.0 - candidate.probability_up
        )
        spot_crossed = (
            spot is not None
            and price_to_beat is not None
            and (
                (side == "down" and spot > price_to_beat)
                or (side == "up" and spot < price_to_beat)
            )
        )
        if held_probability >= bid - exit_fee_per_share and not spot_crossed:
            return None

        size = float(row["size"])
        entry_price = float(row["price"])
        entry_fee = float(row["fee"])
        exit_fee = exit_fee_per_share * size
        pnl = bid * size - entry_price * size - entry_fee - exit_fee
        if not self._store.close_trade(
            int(row["id"]), exit_price=bid, exit_fee=exit_fee, pnl=pnl
        ):
            return None
        logger.info(
            "paper exit model=%s slug=%s side=%s entry_price=%.4f exit_bid=%.4f pnl=%.4f",
            candidate.model,
            slug,
            side,
            entry_price,
            bid,
            pnl,
        )
        return TradeRecord(
            prediction_id=int(row["prediction_id"]),
            model=candidate.model,
            mode="paper",
            side=side,
            price=entry_price,
            size=size,
            fee=entry_fee,
            order_id=row["order_id"],
            fill_price=float(row["fill_price"]) if row["fill_price"] is not None else None,
            pnl=pnl,
            exit_price=bid,
            exit_fee=exit_fee,
        )

    def _record_attempt(
        self,
        *,
        prediction_id: int,
        candidate: Candidate,
        decision: EntryDecision,
        stake_usd: float,
        attempt: AttemptContext | None,
        fill_price: float | None = None,
        outcome: str | None = None,
    ) -> None:
        if attempt is None or decision.reason == "already_traded":
            return
        side = decision.side
        snapshot_ask = None
        if side is not None:
            snapshot_ask = attempt.snapshot_up_ask if side == "up" else attempt.snapshot_down_ask
        plan = decision.plan
        try:
            self._store.add_entry_attempt(
                EntryAttempt(
                    prediction_id=prediction_id,
                    model=candidate.model,
                    mode=self._mode,
                    side=side,
                    outcome=outcome or decision.reason,
                    snapshot_ask=snapshot_ask,
                    fresh_ask=decision.fresh_ask,
                    max_price=decision.max_price,
                    depth_to_max_usd=decision.depth_to_max_usd,
                    stake_usd=stake_usd,
                    fill_price=fill_price if fill_price is not None else (
                        plan.price if plan is not None and outcome is None else None
                    ),
                    lag_ms=(
                        (attempt.decided_at - attempt.snapshot_ts) * 1000
                        if attempt.snapshot_ts
                        else None
                    ),
                    ts=attempt.decided_at,
                )
            )
        except Exception:
            logger.exception("failed to record entry attempt model=%s", candidate.model)

    def execute(
        self,
        *,
        slug: str,
        prediction_id: int,
        candidate: Candidate,
        up_ask: float | None,
        down_ask: float | None,
        edge: float,
        fee_rate: float | None = None,
        fee_exponent: int = 1,
        stake_usd: float,
        spot: float | None = None,
        feature_spot: float | None = None,
        price_to_beat: float | None = None,
        market_probability_up: float | None = None,
        max_model_market_gap: float | None = None,
        up_levels: Levels | None = None,
        down_levels: Levels | None = None,
        attempt: AttemptContext | None = None,
    ) -> TradeRecord | None:
        if candidate.model in {"deepseek", "deepseek_direct"} and self._mode != "paper":
            raise ValueError("DeepSeek execution is restricted to paper mode")
        if self._mode == "live":
            raise RuntimeError("live execution must use await execute_async(...)")
        if self._mode not in {"paper", "shadow"}:
            raise ValueError(f"Unknown executor mode: {self._mode}")
        decision = self._entry_plan(
            slug=slug,
            candidate=candidate,
            up_ask=up_ask,
            down_ask=down_ask,
            edge=edge,
            fee_rate=fee_rate,
            fee_exponent=fee_exponent,
            stake_usd=stake_usd,
            spot=spot,
            feature_spot=feature_spot,
            price_to_beat=price_to_beat,
            market_probability_up=market_probability_up,
            max_model_market_gap=max_model_market_gap,
            check_model_daily_loss=True,
            up_levels=up_levels,
            down_levels=down_levels,
        )
        self._record_attempt(
            prediction_id=prediction_id,
            candidate=candidate,
            decision=decision,
            stake_usd=stake_usd,
            attempt=attempt,
        )
        plan = decision.plan
        if plan is None:
            return None
        trade = TradeRecord(
            prediction_id=prediction_id,
            model=candidate.model,
            mode=self._mode,
            side=plan.side,
            price=plan.price,
            size=plan.size,
            fee=plan.fee,
            fill_price=plan.price,
        )
        self._store.add_trade(trade)
        return trade

    def _max_entry_price(
        self,
        candidate: Candidate,
        side: Side,
        edge: float,
        rate: float,
        exponent: int,
    ) -> float:
        """Highest ask level worth crossing, after simulated slippage and taker fee."""

        if candidate.rule_based:
            cap = candidate.max_price if candidate.max_price is not None else 0.99
            return round(min(0.99, cap), 4)
        held = candidate.probability_up if side == "up" else 1.0 - candidate.probability_up
        slip = self._slippage if self._mode != "live" else 0.0
        steps = round(0.99 / TICK)
        for step in range(steps, 0, -1):
            level = step * TICK
            fill = min(0.99, level + slip)
            if held - fill - fee_per_share(fill, rate, exponent) > edge:
                return round(level, 4)
        return 0.0

    def _walk_book(
        self,
        levels: Levels,
        *,
        max_price: float,
        stake_usd: float,
        rate: float,
        exponent: int,
    ) -> tuple[float, float, float, float]:
        """Spend ``stake_usd`` up the ask ladder; return (vwap, shares, fee, depth_usd).

        ``shares`` is zero when the ladder up to ``max_price`` cannot absorb the stake
        (a fill-or-kill order would be rejected). ``depth_usd`` is the notional that
        was available at or below ``max_price``.
        """

        slip = self._slippage if self._mode != "live" else 0.0
        eligible = [
            (min(0.99, price + slip), size)
            for price, size in sorted(levels)
            if price <= max_price + 1e-9 and size > 0
        ]
        depth_usd = sum(price * size for price, size in eligible)
        remaining = stake_usd
        shares = 0.0
        fee = 0.0
        for price, size in eligible:
            take_usd = min(remaining, price * size)
            take_shares = take_usd / price
            shares += take_shares
            fee += fee_per_share(price, rate, exponent) * take_shares
            remaining -= take_usd
            if remaining <= 1e-9:
                break
        if remaining > 1e-9 or shares <= 0:
            return 0.0, 0.0, 0.0, depth_usd
        return stake_usd / shares, shares, fee, depth_usd

    def _entry_plan(
        self,
        *,
        slug: str,
        candidate: Candidate,
        up_ask: float | None,
        down_ask: float | None,
        edge: float,
        fee_rate: float | None,
        fee_exponent: int,
        stake_usd: float,
        spot: float | None,
        feature_spot: float | None,
        price_to_beat: float | None,
        market_probability_up: float | None,
        max_model_market_gap: float | None,
        check_model_daily_loss: bool,
        up_levels: Levels | None = None,
        down_levels: Levels | None = None,
    ) -> EntryDecision:
        if self._store.has_trade(slug, candidate.model):
            return EntryDecision(None, "already_traded")
        if stake_usd <= 0:
            raise ValueError("stake_usd must be positive")
        if candidate.rule_based and candidate.requested_side is None:
            raise ValueError("rule-based candidates must request a side")

        if (
            spot is not None
            and feature_spot is not None
            and price_to_beat is not None
            and (spot >= price_to_beat) != (feature_spot >= price_to_beat)
        ):
            logger.info(
                "entry skipped: reference and feature feeds straddle target "
                "model=%s slug=%s reference_spot=%.6g feature_spot=%.6g "
                "price_to_beat=%.6g",
                candidate.model,
                slug,
                spot,
                feature_spot,
                price_to_beat,
            )
            return EntryDecision(None, "feeds_straddle", candidate.requested_side)

        if market_probability_up is not None and max_model_market_gap is not None:
            if not 0.0 <= market_probability_up <= 1.0:
                raise ValueError("market_probability_up must be between zero and one")
            if not 0.0 <= max_model_market_gap <= 1.0:
                raise ValueError("max_model_market_gap must be between zero and one")
            raw_probability = (
                candidate.raw_probability_up
                if candidate.raw_probability_up is not None
                else candidate.probability_up
            )
            probability_gap = abs(raw_probability - market_probability_up)
            if not candidate.rule_based and probability_gap > max_model_market_gap:
                logger.info(
                    "entry skipped: model-market probability gap too large "
                    "model=%s slug=%s model_p_up=%.4f market_p_up=%.4f gap=%.4f "
                    "limit=%.4f",
                    candidate.model,
                    slug,
                    raw_probability,
                    market_probability_up,
                    probability_gap,
                    max_model_market_gap,
                )
                return EntryDecision(None, "model_market_gap", candidate.requested_side)

        slip = self._slippage if self._mode != "live" else 0.0
        effective_rate = fee_rate if fee_rate is not None else self._fee_peak * 4.0
        up_edge = float("-inf")
        if up_ask is not None:
            up_fill = min(0.99, up_ask + slip)
            up_edge = candidate.probability_up - up_fill - fee_per_share(
                up_fill, effective_rate, fee_exponent
            )
        down_edge = float("-inf")
        if down_ask is not None:
            down_fill = min(0.99, down_ask + slip)
            down_edge = (1.0 - candidate.probability_up) - down_fill - fee_per_share(
                down_fill, effective_rate, fee_exponent
            )
        if candidate.requested_side == "up":
            side: Side = "up"
            selected_edge = up_edge
        elif candidate.requested_side == "down":
            side = "down"
            selected_edge = down_edge
        elif up_edge >= down_edge:
            side = "up"
            selected_edge = up_edge
        else:
            side = "down"
            selected_edge = down_edge
        top_ask = up_ask if side == "up" else down_ask
        if top_ask is None or selected_edge == float("-inf"):
            return EntryDecision(None, "no_ask", side)
        if top_ask <= 0:
            raise ValueError("ask price must be positive")
        max_price = self._max_entry_price(
            candidate, side, edge, effective_rate, fee_exponent
        )
        if candidate.rule_based:
            if top_ask > max_price + 1e-9:
                return EntryDecision(None, "no_edge", side, top_ask, max_price)
        elif selected_edge <= edge:
            return EntryDecision(None, "no_edge", side, top_ask, max_price)

        now = time.time()
        settled = self._store.settled_pnl(candidate.model, utc_day_start(now))
        if check_model_daily_loss and settled <= -self._daily_loss_limit_usd:
            logger.info(
                "model blocked by daily loss model=%s pnl=%.2f limit=%.2f",
                candidate.model,
                settled,
                self._daily_loss_limit_usd,
            )
            return EntryDecision(None, "daily_loss", side, top_ask, max_price)
        if (
            spot is not None
            and price_to_beat is not None
            and (
                (side == "down" and spot > price_to_beat)
                or (side == "up" and spot < price_to_beat)
            )
        ):
            logger.info(
                "entry skipped: spot on other side model=%s side=%s "
                "spot=%.6g price_to_beat=%.6g",
                candidate.model,
                side,
                spot,
                price_to_beat,
            )
            return EntryDecision(None, "spot_other_side", side, top_ask, max_price)

        levels = up_levels if side == "up" else down_levels
        if levels:
            price, size, total_fee, depth_usd = self._walk_book(
                levels,
                max_price=max_price,
                stake_usd=stake_usd,
                rate=effective_rate,
                exponent=fee_exponent,
            )
            if size <= 0:
                logger.info(
                    "entry skipped: book too thin model=%s side=%s depth_usd=%.2f "
                    "max_price=%.2f stake=%.2f",
                    candidate.model,
                    side,
                    depth_usd,
                    max_price,
                    stake_usd,
                )
                return EntryDecision(
                    None, "insufficient_depth", side, top_ask, max_price, depth_usd
                )
        else:
            price = min(0.99, top_ask + slip)
            size = stake_usd / price
            total_fee = fee_per_share(price, effective_rate, fee_exponent) * size
            depth_usd = None
        return EntryDecision(
            EntryPlan(side=side, price=price, size=size, fee=total_fee, max_price=max_price),
            "filled",
            side,
            top_ask,
            max_price,
            depth_usd,
        )

    async def execute_async(
        self,
        *,
        slug: str,
        prediction_id: int,
        candidate: Candidate,
        up_ask: float | None,
        down_ask: float | None,
        edge: float,
        fee_rate: float | None = None,
        fee_exponent: int = 1,
        stake_usd: float,
        up_token: str | None = None,
        down_token: str | None = None,
        reference_timestamp: float | None = None,
        spot: float | None = None,
        feature_spot: float | None = None,
        price_to_beat: float | None = None,
        market_probability_up: float | None = None,
        max_model_market_gap: float | None = None,
        up_levels: Levels | None = None,
        down_levels: Levels | None = None,
        attempt: AttemptContext | None = None,
    ) -> TradeRecord | None:
        """Execute synchronously simulated modes or one serialized live FOK order."""

        if candidate.model in {"deepseek", "deepseek_direct"} and self._mode != "paper":
            raise ValueError("DeepSeek execution is restricted to paper mode")
        if self._mode != "live":
            return await asyncio.to_thread(
                self.execute,
                slug=slug,
                prediction_id=prediction_id,
                candidate=candidate,
                up_ask=up_ask,
                down_ask=down_ask,
                edge=edge,
                fee_rate=fee_rate,
                fee_exponent=fee_exponent,
                stake_usd=stake_usd,
                spot=spot,
                feature_spot=feature_spot,
                price_to_beat=price_to_beat,
                market_probability_up=market_probability_up,
                max_model_market_gap=max_model_market_gap,
                up_levels=up_levels,
                down_levels=down_levels,
                attempt=attempt,
            )
        if self._live_gateway is None or self._live_risk is None:
            raise RuntimeError("live executor is missing its gateway or risk guard")
        if reference_timestamp is None:
            raise ValueError("live execution requires a reference feed timestamp")

        async with self._live_lock:
            decision = await asyncio.to_thread(
                self._entry_plan,
                slug=slug,
                candidate=candidate,
                up_ask=up_ask,
                down_ask=down_ask,
                edge=edge,
                fee_rate=fee_rate,
                fee_exponent=fee_exponent,
                stake_usd=stake_usd,
                spot=spot,
                feature_spot=feature_spot,
                price_to_beat=price_to_beat,
                market_probability_up=market_probability_up,
                max_model_market_gap=max_model_market_gap,
                check_model_daily_loss=False,
                up_levels=up_levels,
                down_levels=down_levels,
            )
            plan = decision.plan
            if plan is None:
                self._record_attempt(
                    prediction_id=prediction_id,
                    candidate=candidate,
                    decision=decision,
                    stake_usd=stake_usd,
                    attempt=attempt,
                )
                return None
            if plan.size < self._live_min_shares:
                logger.info(
                    "live entry skipped: %.2f shares below minimum %.2f model=%s slug=%s",
                    plan.size,
                    self._live_min_shares,
                    candidate.model,
                    slug,
                )
                self._record_attempt(
                    prediction_id=prediction_id,
                    candidate=candidate,
                    decision=decision,
                    stake_usd=stake_usd,
                    attempt=attempt,
                    outcome="below_min_shares",
                )
                return None
            reason = await asyncio.to_thread(
                self._live_risk.block_reason,
                now=time.time(),
                requested_notional=stake_usd,
                reference_timestamp=reference_timestamp,
            )
            if reason is not None:
                logger.error("live order blocked: %s", reason)
                self._record_attempt(
                    prediction_id=prediction_id,
                    candidate=candidate,
                    decision=decision,
                    stake_usd=stake_usd,
                    attempt=attempt,
                    outcome="risk_blocked",
                )
                return None
            token_id = up_token if plan.side == "up" else down_token
            if not token_id:
                raise ValueError(f"live execution has no {plan.side} token id")
            try:
                # The limit is the highest price that still clears the edge, not
                # the (possibly stale) ask; FOK rejects if the book cannot fill.
                result = await self._live_gateway.buy_fok(
                    token_id=token_id,
                    amount_usd=stake_usd,
                    max_price=plan.max_price,
                )
            except asyncio.CancelledError:
                self._live_risk.latch(
                    "live order was cancelled during submission; inspect CLOB account "
                    "before restart"
                )
                raise
            except Exception as exc:
                self._live_risk.latch(
                    "ambiguous live order transport failure; inspect CLOB account before restart"
                )
                raise RuntimeError("live order failed and execution is now latched") from exc
            if result is None:
                self._record_attempt(
                    prediction_id=prediction_id,
                    candidate=candidate,
                    decision=decision,
                    stake_usd=stake_usd,
                    attempt=attempt,
                    outcome="fok_rejected",
                )
                return None
            if result.status != "matched" or result.fill_price is None or result.size <= 0:
                pending = TradeRecord(
                    prediction_id=prediction_id,
                    model=candidate.model,
                    mode="live",
                    side=plan.side,
                    price=plan.price,
                    size=plan.size,
                    fee=plan.fee,
                    order_id=result.order_id,
                    execution_status=result.status,
                )
                await asyncio.to_thread(self._store.add_trade, pending)
                self._record_attempt(
                    prediction_id=prediction_id,
                    candidate=candidate,
                    decision=decision,
                    stake_usd=stake_usd,
                    attempt=attempt,
                    outcome="pending",
                )
                self._live_risk.latch(
                    f"live order {result.order_id} returned {result.status}; reconcile manually"
                )
                logger.error("live order accepted without confirmed fill: %s", result.order_id)
                return None

            effective_rate = fee_rate if fee_rate is not None else self._fee_peak * 4.0
            total_fee = (
                fee_per_share(result.fill_price, effective_rate, fee_exponent) * result.size
            )
            trade = TradeRecord(
                prediction_id=prediction_id,
                model=candidate.model,
                mode="live",
                side=plan.side,
                price=result.fill_price,
                size=result.size,
                fee=total_fee,
                order_id=result.order_id,
                fill_price=result.fill_price,
                execution_status="matched",
            )
            await asyncio.to_thread(self._store.add_trade, trade)
            self._record_attempt(
                prediction_id=prediction_id,
                candidate=candidate,
                decision=decision,
                stake_usd=stake_usd,
                attempt=attempt,
                fill_price=result.fill_price,
            )
            logger.warning(
                "LIVE FILL model=%s slug=%s side=%s price=%.4f size=%.4f order=%s",
                candidate.model,
                slug,
                plan.side,
                result.fill_price,
                result.size,
                result.order_id,
            )
            return trade

    async def close(self) -> None:
        if self._live_gateway is not None:
            await self._live_gateway.close()
