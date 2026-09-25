#!/usr/bin/env python3
"""Print raw Polymarket Chainlink WS frames; intentionally performs no parsing."""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import websockets

from pmjev.feeds.chainlink import build_subscription


async def probe(url: str, symbols: list[str], topic: str, messages: int) -> None:
    print(json.dumps({"local_time": time.time(), "url": url, "symbols": symbols, "topic": topic}))
    async with websockets.connect(url) as websocket:
        subscription = build_subscription(symbols, topic)
        print("SUBSCRIBE", json.dumps(subscription))
        await websocket.send(json.dumps(subscription))
        for _ in range(messages):
            raw = await asyncio.wait_for(websocket.recv(), timeout=20)
            print("FRAME", time.time(), raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="wss://ws-live-data.polymarket.com")
    parser.add_argument("--symbols", default="btc/usd,eth/usd,sol/usd,hype/usd")
    parser.add_argument("--topic", default="crypto_prices_twap_sixty")
    parser.add_argument("--messages", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(probe(args.url, args.symbols.lower().split(","), args.topic, args.messages))


if __name__ == "__main__":
    main()
