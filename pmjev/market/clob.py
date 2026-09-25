"""Read-only CLOB order book adapter for Phase 0/1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    up_bid: float | None
    up_ask: float
    down_bid: float | None
    down_ask: float
    depth_ask_usd: float


def _levels(payload: dict[str, Any], side: str) -> list[tuple[float, float]]:
    raw_levels = payload.get(side, [])
    if not isinstance(raw_levels, list):
        return []
    return [
        (float(level["price"]), float(level["size"]))
        for level in raw_levels
        if isinstance(level, dict) and "price" in level and "size" in level
    ]


class ClobClient:
    """Public book reads only; live order methods are deliberately absent."""

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def _book(self, token_id: str) -> dict[str, Any]:
        response = await self._client.get(f"{self._base_url}/book", params={"token_id": token_id})
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload

    async def snapshot(self, up_token: str, down_token: str) -> BookSnapshot:
        import asyncio

        up_book, down_book = await asyncio.gather(self._book(up_token), self._book(down_token))
        up_bids = _levels(up_book, "bids")
        up_asks = _levels(up_book, "asks")
        down_bids = _levels(down_book, "bids")
        down_asks = _levels(down_book, "asks")
        if not up_asks or not down_asks:
            raise ValueError("CLOB returned an empty ask side of the order book")
        up_bid = max((price for price, _ in up_bids), default=None)
        up_ask = min(price for price, _ in up_asks)
        down_bid = max((price for price, _ in down_bids), default=None)
        down_ask = min(price for price, _ in down_asks)
        depth_ask_usd = sum(price * size for price, size in up_asks if price == up_ask)
        return BookSnapshot(
            up_bid=up_bid,
            up_ask=up_ask,
            down_bid=down_bid,
            down_ask=down_ask,
            depth_ask_usd=depth_ask_usd,
        )
