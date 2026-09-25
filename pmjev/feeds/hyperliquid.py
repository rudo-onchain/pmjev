"""Hyperliquid public info API feature adapter."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from contextlib import suppress
from typing import Any

import httpx
import websockets

from pmjev.feeds.base import Candle, Trade

logger = logging.getLogger(__name__)


def candle_request(coin: str, start: float, end: float) -> dict[str, Any]:
    """Build the verified HYPE ``candleSnapshot`` request."""
    return {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": "1m",
            "startTime": int(start * 1000),
            "endTime": int(end * 1000),
        },
    }


def recent_trades_request(coin: str) -> dict[str, str]:
    return {"type": "recentTrades", "coin": coin}


class HyperliquidFeed:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        ws_url: str,
        coin: str,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._ws_url = ws_url
        self._coin = coin
        self._trades: deque[Trade] = deque(maxlen=100_000)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        subscription = {
            "method": "subscribe",
            "subscription": {"type": "trades", "coin": self._coin},
        }
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._ws_url) as websocket:
                    await websocket.send(json.dumps(subscription))
                    async for raw in websocket:
                        payload: dict[str, Any] = json.loads(raw)
                        if payload.get("channel") != "trades":
                            continue
                        data = payload.get("data", [])
                        if not isinstance(data, list):
                            continue
                        for row in data:
                            if not isinstance(row, dict):
                                continue
                            self._trades.append(
                                Trade(
                                    timestamp=float(row["time"]) / 1000,
                                    price=float(row["px"]),
                                    quantity=float(row["sz"]),
                                    is_buyer_maker=str(row["side"]).upper() != "B",
                                )
                            )
                        if self._stop.is_set():
                            return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Hyperliquid trade stream disconnected: %s", self._coin)
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1)

    def close(self) -> None:
        self._stop.set()

    async def candles(self, *, start: float, end: float) -> list[Candle]:
        response = await self._client.post(
            f"{self._base_url}/info",
            json=candle_request(self._coin, start, end),
        )
        response.raise_for_status()
        rows: list[dict[str, Any]] = response.json()
        return [
            Candle(
                open_time=float(row["t"]) / 1000,
                close_time=float(row["T"]) / 1000,
                open=float(row["o"]),
                high=float(row["h"]),
                low=float(row["l"]),
                close=float(row["c"]),
                volume=float(row["v"]),
            )
            for row in rows
        ]

    async def trades(self, *, start: float, end: float) -> list[Trade]:
        streamed = [trade for trade in self._trades if start <= trade.timestamp <= end]
        if streamed:
            return streamed
        response = await self._client.post(
            f"{self._base_url}/info",
            json=recent_trades_request(self._coin),
        )
        response.raise_for_status()
        rows: list[dict[str, Any]] = response.json()
        parsed = [
            Trade(
                timestamp=float(row["time"]) / 1000,
                price=float(row["px"]),
                quantity=float(row["sz"]),
                # Hyperliquid side B is buyer-initiated; normalize to Binance's
                # is_buyer_maker convention used by the common feature builder.
                is_buyer_maker=str(row["side"]).upper() != "B",
            )
            for row in rows
        ]
        return [trade for trade in parsed if start <= trade.timestamp <= end]
