"""Authenticated PolyBolt 60-second TWAP reference-price stream."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import defaultdict, deque
from contextlib import suppress
from datetime import datetime
from decimal import Decimal
from typing import Any

import websockets

from pmjev.feeds.chainlink import PriceTick, select_price_to_beat

logger = logging.getLogger(__name__)


def canonical_symbol(symbol: str) -> str:
    """Return PolyBolt's lowercase no-separator crypto symbol."""

    return "".join(character for character in symbol.lower() if character.isalnum())


def build_auth(
    *, api_key: str, secret: str, passphrase: str, rid: str = "auth-1"
) -> dict[str, Any]:
    return {
        "op": "auth",
        "rid": rid,
        "auth": {"apiKey": api_key, "secret": secret, "passphrase": passphrase},
    }


def build_twap_subscription(symbols: list[str], rid: str = "twap-1") -> dict[str, Any]:
    """Subscribe to every configured asset in one PolyBolt frame/connection."""

    return {
        "op": "subscribe",
        "rid": rid,
        "subscriptions": [
            {
                "channel": "price.crypto.twap",
                "filter": {"symbol": canonical_symbol(symbol), "window_seconds": 60},
            }
            for symbol in symbols
        ],
    }


def _timestamp(value: object) -> float:
    if isinstance(value, (int, float)):
        timestamp = float(value)
        return timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
    if isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        return numeric / 1000 if numeric > 10_000_000_000 else numeric
    raise ValueError("PolyBolt timestamp is missing or invalid")


def parse_polybolt_message(raw: str | bytes) -> list[PriceTick]:
    """Parse PolyBolt TWAP snapshots and updates into the existing tick model."""

    if not raw:
        return []
    decoded: Any = json.loads(raw)
    messages = decoded if isinstance(decoded, list) else [decoded]
    ticks: list[PriceTick] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("op") in {"authed", "subscribed", "pong"}:
            continue
        if message.get("op") in {"error", "failed"} or message.get("error"):
            detail = message.get("error") or message.get("message") or message
            raise ValueError(f"PolyBolt rejected request: {detail}")
        if message.get("topic") not in (None, "prices.crypto.twap"):
            continue
        payload = message.get("payload")
        if not isinstance(payload, dict):
            continue
        symbol = payload.get("symbol")
        if symbol is None:
            continue
        history = payload.get("data")
        points = history if isinstance(history, list) else [payload]
        for point in points:
            if not isinstance(point, dict):
                continue
            value = point.get("value")
            timestamp = point.get("timestamp")
            if value is None or timestamp is None:
                continue
            ticks.append(
                PriceTick(
                    symbol=canonical_symbol(str(symbol)),
                    price=float(Decimal(str(value))),
                    timestamp=_timestamp(timestamp),
                )
            )
    return ticks


class PolyBoltFeed:
    """One authenticated, reconnecting PolyBolt connection for all assets."""

    def __init__(
        self,
        url: str,
        symbols: list[str],
        *,
        api_key: str,
        secret: str,
        passphrase: str,
        history_size: int = 20_000,
    ) -> None:
        self._url = url
        self._symbols = sorted({canonical_symbol(symbol) for symbol in symbols})
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase
        self._history: dict[str, deque[PriceTick]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._stop = asyncio.Event()
        self.connected = asyncio.Event()

    async def _authenticate(self, websocket: Any) -> None:
        rid = "auth-1"
        await websocket.send(
            json.dumps(
                build_auth(
                    api_key=self._api_key,
                    secret=self._secret,
                    passphrase=self._passphrase,
                    rid=rid,
                )
            )
        )
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            message: Any = json.loads(raw)
            if isinstance(message, dict) and message.get("op") == "authed" and message.get(
                "rid"
            ) == rid:
                return
            if isinstance(message, dict) and (
                message.get("op") in {"error", "failed"} or message.get("error")
            ):
                detail = message.get("error") or message.get("message") or message
                raise RuntimeError(f"PolyBolt authentication failed: {detail}")

    async def run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._url) as websocket:
                    await self._authenticate(websocket)
                    await websocket.send(
                        json.dumps(build_twap_subscription(self._symbols), separators=(",", ":"))
                    )
                    self.connected.set()
                    delay = 1.0
                    async for raw in websocket:
                        for tick in parse_polybolt_message(raw):
                            if tick.symbol in self._symbols:
                                self._history[tick.symbol].append(tick)
                        if self._stop.is_set():
                            return
            except asyncio.CancelledError:
                raise
            except Exception:
                self.connected.clear()
                logger.exception("PolyBolt reference feed disconnected")
                wait = delay + random.uniform(0, delay * 0.25)
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
                delay = min(delay * 2, 30.0)
            finally:
                self.connected.clear()

    def history(self, symbol: str, *, since: float | None = None) -> list[PriceTick]:
        ticks = list(self._history[canonical_symbol(symbol)])
        if since is None:
            return ticks
        return [tick for tick in ticks if tick.timestamp >= since]

    def latest(self, symbol: str) -> PriceTick | None:
        ticks = self._history[canonical_symbol(symbol)]
        return ticks[-1] if ticks else None

    def price_to_beat(self, symbol: str, window_start: int) -> PriceTick | None:
        return select_price_to_beat(self.history(symbol, since=window_start), window_start)

    def close(self) -> None:
        self._stop.set()
