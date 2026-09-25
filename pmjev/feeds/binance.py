"""Binance public REST feature adapter."""

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


class BinanceFeed:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        ws_url: str,
        symbol: str,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._ws_url = ws_url.rstrip("/")
        self._symbol = symbol.upper()
        self._trades: deque[Trade] = deque(maxlen=100_000)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        stream_url = f"{self._ws_url}/{self._symbol.lower()}@trade"
        while not self._stop.is_set():
            try:
                async with websockets.connect(stream_url) as websocket:
                    async for raw in websocket:
                        payload: dict[str, Any] = json.loads(raw)
                        self._trades.append(
                            Trade(
                                timestamp=float(payload["T"]) / 1000,
                                price=float(payload["p"]),
                                quantity=float(payload["q"]),
                                is_buyer_maker=bool(payload["m"]),
                            )
                        )
                        if self._stop.is_set():
                            return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Binance trade stream disconnected: %s", self._symbol)
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1)

    def close(self) -> None:
        self._stop.set()

    async def candles(self, *, start: float, end: float) -> list[Candle]:
        response = await self._client.get(
            f"{self._base_url}/api/v3/klines",
            params={
                "symbol": self._symbol,
                "interval": "1m",
                "startTime": int(start * 1000),
                "endTime": int(end * 1000),
                "limit": 1000,
            },
        )
        response.raise_for_status()
        rows: list[list[Any]] = response.json()
        return [
            Candle(
                open_time=float(row[0]) / 1000,
                close_time=float(row[6]) / 1000,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]

    async def trades(self, *, start: float, end: float) -> list[Trade]:
        streamed = [trade for trade in self._trades if start <= trade.timestamp <= end]
        if streamed:
            return streamed
        response = await self._client.get(
            f"{self._base_url}/api/v3/aggTrades",
            params={
                "symbol": self._symbol,
                "startTime": int(start * 1000),
                "endTime": int(end * 1000),
                "limit": 1000,
            },
        )
        response.raise_for_status()
        rows: list[dict[str, Any]] = response.json()
        return [
            Trade(
                timestamp=float(row["T"]) / 1000,
                price=float(row["p"]),
                quantity=float(row["q"]),
                is_buyer_maker=bool(row["m"]),
            )
            for row in rows
        ]
