"""Execution-mode boundary. Only paper mode exists in Phase 0/1."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pmjev.store import Store, TradeRecord

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


def utc_day_start(now: float) -> float:
    """Return the UTC midnight timestamp that starts the day containing ``now``."""

    moment = datetime.fromtimestamp(now, tz=UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class Executor:
    def __init__(
        self,
        mode: str,
        store: Store,
        fee_peak: float,
        daily_loss_limit_usd: float = 25.0,
    ) -> None:
        self._mode = mode
        self._store = store
        self._fee_peak = fee_peak
        self._daily_loss_limit_usd = daily_loss_limit_usd

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
        if self._mode == "shadow":
            raise NotImplementedError("shadow execution belongs to Phase 2")
        if self._mode == "live":
            raise NotImplementedError("live execution belongs to Phase 3")
        if self._mode != "paper":
            raise ValueError(f"Unknown executor mode: {self._mode}")
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
        if settled <= -self._daily_loss_limit_usd:
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
        trade = TradeRecord(
            prediction_id=prediction_id,
            model=candidate.model,
            mode="paper",
            side=side,
            price=price,
            size=size,
            fee=total_fee,
            fill_price=price,
        )
        self._store.add_trade(trade)
        return trade
