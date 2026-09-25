"""Polymarket RTDS 60-second-TWAP stream and boundary-price selection."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import websockets

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PriceTick:
    symbol: str
    price: float
    timestamp: float


def build_subscription(symbols: list[str], topic: str) -> dict[str, Any]:
    """Return the verified RTDS payload with string-encoded symbol filters."""

    return {
        "action": "subscribe",
        "subscriptions": [
            {
                "topic": topic,
                "type": "*" if topic == "crypto_prices_chainlink" else "update",
                "filters": json.dumps({"symbol": symbol}, separators=(",", ":")),
            }
            for symbol in symbols
        ],
    }


def parse_chainlink_message(raw: str | bytes) -> list[PriceTick]:
    """Parse verified RTDS update and subscription-snapshot envelopes."""

    if not raw or raw in ("PING", "PONG", b"PING", b"PONG"):
        return []
    payload: Any = json.loads(raw)
    candidates = payload if isinstance(payload, list) else [payload]
    ticks: list[PriceTick] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if "message" in candidate:
            raise ValueError(f"RTDS rejected request: {candidate['message']}")
        data = candidate.get("payload", candidate.get("data", candidate))
        if not isinstance(data, dict):
            continue
        snapshot = data.get("data")
        points = snapshot if isinstance(snapshot, list) else [data]
        parent_symbol = data.get("symbol") or data.get("pair")
        for point in points:
            if not isinstance(point, dict):
                continue
            symbol = point.get("symbol") or point.get("pair") or parent_symbol
            timestamp = point.get("timestamp") or point.get("ts")
            if symbol is None or timestamp is None:
                continue
            if point.get("full_accuracy_value") is not None:
                price = Decimal(str(point["full_accuracy_value"])) / Decimal(10**18)
            else:
                raw_price = point.get("price") or point.get("value")
                if raw_price is None:
                    continue
                price = Decimal(str(raw_price))
            numeric_timestamp = float(timestamp)
            if numeric_timestamp > 10_000_000_000:
                numeric_timestamp /= 1000
            ticks.append(
                PriceTick(
                    symbol=str(symbol).lower(),
                    price=float(price),
                    timestamp=numeric_timestamp,
                )
            )
    return ticks


def select_price_to_beat(ticks: list[PriceTick], window_start: int) -> PriceTick | None:
    """Select the first observed tick at or after the boundary.

    TODO(api-verification): verify whether Polymarket uses the first Chainlink tick at or
    after the boundary or the last tick before it. Probe scripts print raw timestamps.
    """

    eligible = [tick for tick in ticks if tick.timestamp >= window_start]
    return min(eligible, key=lambda tick: tick.timestamp, default=None)


class ChainlinkFeed:
    def __init__(
        self, url: str, symbols: list[str], topic: str, history_size: int = 20_000
    ) -> None:
        self._url = url
        self._symbols = [symbol.lower() for symbol in symbols]
        self._topic = topic
        self._history: dict[str, deque[PriceTick]] = defaultdict(lambda: deque(maxlen=history_size))
        self._stop = asyncio.Event()
        self._connected_symbols: set[str] = set()
        self.connected = asyncio.Event()

    async def run(self) -> None:
        """Run one independently reconnecting RTDS connection per symbol."""

        await asyncio.gather(*(self._run_symbol(symbol) for symbol in self._symbols))

    async def _run_symbol(self, symbol: str) -> None:
        """Reconnect one symbol forever until ``close`` is called."""

        while not self._stop.is_set():
            try:
                async with websockets.connect(self._url) as websocket:
                    await websocket.send(json.dumps(build_subscription([symbol], self._topic)))
                    self._connected_symbols.add(symbol)
                    if len(self._connected_symbols) == len(self._symbols):
                        self.connected.set()

                    async def heartbeat() -> None:
                        while not self._stop.is_set():
                            await asyncio.sleep(5)
                            await websocket.send("PING")

                    heartbeat_task = asyncio.create_task(heartbeat())
                    try:
                        async for raw in websocket:
                            for tick in parse_chainlink_message(raw):
                                if tick.symbol == symbol:
                                    self._history[tick.symbol].append(tick)
                            if self._stop.is_set():
                                return
                    finally:
                        self._connected_symbols.discard(symbol)
                        self.connected.clear()
                        heartbeat_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await heartbeat_task
            except asyncio.CancelledError:
                raise
            except Exception:
                self._connected_symbols.discard(symbol)
                self.connected.clear()
                logger.exception("chainlink feed disconnected symbol=%s", symbol)
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)

    def history(self, symbol: str, *, since: float | None = None) -> list[PriceTick]:
        ticks = list(self._history[symbol.lower()])
        if since is None:
            return ticks
        return [tick for tick in ticks if tick.timestamp >= since]

    def latest(self, symbol: str) -> PriceTick | None:
        ticks = self._history[symbol.lower()]
        return ticks[-1] if ticks else None

    def price_to_beat(self, symbol: str, window_start: int) -> PriceTick | None:
        return select_price_to_beat(self.history(symbol, since=window_start), window_start)

    def close(self) -> None:
        self._stop.set()
