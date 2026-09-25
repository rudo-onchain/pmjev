"""Feature-state construction shared by all predictors."""

from __future__ import annotations

import asyncio
import math
import statistics
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from pmjev.feeds.base import Candle, FeatureSource, Trade


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    state: dict[str, Any]
    feature_spot: float
    sigma_1s: float


def _price_at_or_before(
    candles: list[Candle], trades: list[Trade], timestamp: float
) -> float | None:
    points = [(candle.close_time, candle.close) for candle in candles]
    points.extend((trade.timestamp, trade.price) for trade in trades)
    eligible = [(ts, price) for ts, price in points if ts <= timestamp]
    return max(eligible, default=(0.0, 0.0), key=lambda point: point[0])[1] or None


def _return_pct(
    current: float, candles: list[Candle], trades: list[Trade], timestamp: float
) -> float:
    previous = _price_at_or_before(candles, trades, timestamp)
    if previous is None or previous <= 0:
        return 0.0
    return (current / previous - 1.0) * 100


def realized_sigma_1s(candles: list[Candle]) -> float:
    """Estimate per-second log-return volatility from one-minute closes."""

    closes = [candle.close for candle in sorted(candles, key=lambda value: value.close_time)]
    returns = [math.log(current / previous) for previous, current in pairwise(closes)]
    if len(returns) < 2:
        return 0.0
    return statistics.stdev(returns) / math.sqrt(60.0)


def buy_volume_ratio(trades: list[Trade]) -> float:
    total = sum(trade.quantity for trade in trades)
    if total <= 0:
        return 0.5
    taker_buy = sum(trade.quantity for trade in trades if not trade.is_buyer_maker)
    return taker_buy / total


async def build_features(
    source: FeatureSource,
    *,
    price_to_beat: float,
    chainlink_spot: float,
    now: float,
    seconds_remaining: int,
) -> FeatureSnapshot:
    """Fetch source data concurrently and build the exact Jev state payload."""

    candles, trades = await asyncio.gather(
        source.candles(start=now - 3660, end=now),
        source.trades(start=now - 60, end=now),
    )
    points = [(candle.close_time, candle.close) for candle in candles]
    points.extend((trade.timestamp, trade.price) for trade in trades)
    if not points:
        raise ValueError("feature source returned neither candles nor trades")
    _, feature_spot = max(points, key=lambda point: point[0])
    sigma_1s = realized_sigma_1s(candles)
    recent_trades = [trade for trade in trades if trade.timestamp >= now - 60]
    state: dict[str, Any] = {
        "price_to_beat": price_to_beat,
        "spot": chainlink_spot,
        "pct_from_price_to_beat": (chainlink_spot / price_to_beat - 1.0) * 100,
        "seconds_remaining": seconds_remaining,
        "return_10s_pct": _return_pct(feature_spot, candles, trades, now - 10),
        "return_30s_pct": _return_pct(feature_spot, candles, trades, now - 30),
        "return_60s_pct": _return_pct(feature_spot, candles, trades, now - 60),
        "return_5m_pct": _return_pct(feature_spot, candles, trades, now - 300),
        "return_15m_pct": _return_pct(feature_spot, candles, trades, now - 900),
        "return_60m_pct": _return_pct(feature_spot, candles, trades, now - 3600),
        "realized_volatility_60m_pct_per_minute": sigma_1s * math.sqrt(60) * 100,
        "order_flow_buy_ratio_60s": buy_volume_ratio(recent_trades),
        "chainlink_feature_source_spread_bps": (chainlink_spot / feature_spot - 1.0) * 10_000,
        "market_rule": (
            "The market resolves Up when the closing price is greater than or equal "
            "to price_to_beat."
        ),
    }
    return FeatureSnapshot(state=state, feature_spot=feature_spot, sigma_1s=sigma_1s)
