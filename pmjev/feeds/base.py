"""Common feature-feed interface and value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: float
    close_time: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Trade:
    timestamp: float
    price: float
    quantity: float
    is_buyer_maker: bool


class FeatureSource(Protocol):
    """Adapter boundary for every source used by the feature builder."""

    async def run(self) -> None: ...

    def close(self) -> None: ...

    async def candles(self, *, start: float, end: float) -> list[Candle]: ...

    async def trades(self, *, start: float, end: float) -> list[Trade]: ...
