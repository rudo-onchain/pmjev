"""Paper, shadow, and tightly gated live execution."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pmjev.market.live import LiveOrderGateway
from pmjev.risk import LiveRiskGuard
from pmjev.store import StoreBackend, TradeRecord

logger = logging.getLogger(__name__)

Side = Literal["up", "down"]


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


@dataclass(frozen=True, slots=True)
class Candidate:
    model: str
    probability_up: float


@dataclass(frozen=True, slots=True)
class EntryPlan:
    side: Side
    price: float
    size: float
    fee: float


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
    ) -> None:
        self._mode = mode
        self._store = store
        self._fee_peak = fee_peak
        self._daily_loss_limit_usd = daily_loss_limit_usd
        self._live_gateway = live_gateway
        self._live_risk = live_risk
        self._live_min_shares = live_min_shares
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

        if self._mode != "paper":
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
        price_to_beat: float | None = None,
    ) -> TradeRecord | None:
        if self._mode == "live":
            raise RuntimeError("live execution must use await execute_async(...)")
        if self._mode not in {"paper", "shadow"}:
            raise ValueError(f"Unknown executor mode: {self._mode}")
        plan = self._entry_plan(
            slug=slug,
            candidate=candidate,
            up_ask=up_ask,
            down_ask=down_ask,
            edge=edge,
            fee_rate=fee_rate,
            fee_exponent=fee_exponent,
            stake_usd=stake_usd,
            spot=spot,
            price_to_beat=price_to_beat,
            check_model_daily_loss=True,
        )
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
        price_to_beat: float | None,
        check_model_daily_loss: bool,
    ) -> EntryPlan | None:
        if self._store.has_trade(slug, candidate.model):
            return None

        effective_rate = fee_rate if fee_rate is not None else self._fee_peak * 4.0
        up_edge = float("-inf")
        if up_ask is not None:
            up_fee = fee_per_share(up_ask, effective_rate, fee_exponent)
            up_edge = candidate.probability_up - up_ask - up_fee
        down_edge = float("-inf")
        if down_ask is not None:
            down_fee = fee_per_share(down_ask, effective_rate, fee_exponent)
            down_edge = (1.0 - candidate.probability_up) - down_ask - down_fee
        if max(up_edge, down_edge) <= edge:
            return None
        now = time.time()
        settled = self._store.settled_pnl(candidate.model, utc_day_start(now))
        if check_model_daily_loss and settled <= -self._daily_loss_limit_usd:
            logger.info(
                "model blocked by daily loss model=%s pnl=%.2f limit=%.2f",
                candidate.model,
                settled,
                self._daily_loss_limit_usd,
            )
            return None
        side: Side = "up" if up_edge >= down_edge else "down"
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
            return None
        price = up_ask if side == "up" else down_ask
        if price is None:
            raise RuntimeError("selected an entry side without an ask")
        if price <= 0:
            raise ValueError("ask price must be positive")
        if stake_usd <= 0:
            raise ValueError("stake_usd must be positive")
        size = stake_usd / price
        total_fee = fee_per_share(price, effective_rate, fee_exponent) * size
        return EntryPlan(side=side, price=price, size=size, fee=total_fee)

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
        price_to_beat: float | None = None,
    ) -> TradeRecord | None:
        """Execute synchronously simulated modes or one serialized live FOK order."""

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
                price_to_beat=price_to_beat,
            )
        if self._live_gateway is None or self._live_risk is None:
            raise RuntimeError("live executor is missing its gateway or risk guard")
        if reference_timestamp is None:
            raise ValueError("live execution requires a reference feed timestamp")

        async with self._live_lock:
            plan = await asyncio.to_thread(
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
                price_to_beat=price_to_beat,
                check_model_daily_loss=False,
            )
            if plan is None:
                return None
            if plan.size < self._live_min_shares:
                logger.info(
                    "live entry skipped: %.2f shares below minimum %.2f model=%s slug=%s",
                    plan.size,
                    self._live_min_shares,
                    candidate.model,
                    slug,
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
                return None
            token_id = up_token if plan.side == "up" else down_token
            if not token_id:
                raise ValueError(f"live execution has no {plan.side} token id")
            try:
                result = await self._live_gateway.buy_fok(
                    token_id=token_id,
                    amount_usd=stake_usd,
                    max_price=plan.price,
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
