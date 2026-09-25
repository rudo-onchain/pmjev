#!/usr/bin/env python3
"""Capture raw Chainlink frames around a five-minute boundary.

Start this before the printed boundary. The output retains both local receipt time and
the untouched server frame so the resolution tick rule can be checked manually.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import websockets

from pmjev.feeds.chainlink import build_subscription


async def probe(url: str, symbol: str, topic: str, window_seconds: int, after_seconds: int) -> None:
    now = time.time()
    boundary = int(now) - (int(now) % window_seconds) + window_seconds
    print(
        "BOUNDARY",
        json.dumps(
            {
                "unix": boundary,
                "seconds_until": boundary - now,
                "instruction": "Compare last frame before vs first frame after this timestamp.",
            }
        ),
    )
    async with websockets.connect(url) as websocket:
        subscription = build_subscription([symbol.lower()], topic)
        print("SUBSCRIBE", json.dumps(subscription))
        await websocket.send(json.dumps(subscription))
        deadline = boundary + after_seconds
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=deadline - time.time())
            except TimeoutError:
                break
            print("FRAME", time.time(), raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="wss://ws-live-data.polymarket.com")
    parser.add_argument("--symbol", default="btc/usd")
    parser.add_argument("--topic", default="crypto_prices_twap_sixty")
    parser.add_argument("--window-seconds", type=int, default=300)
    parser.add_argument("--after-seconds", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(
        probe(
            args.url,
            args.symbol,
            args.topic,
            args.window_seconds,
            args.after_seconds,
        )
    )


if __name__ == "__main__":
    main()
