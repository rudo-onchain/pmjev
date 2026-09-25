#!/usr/bin/env python3
"""Print the raw HYPE candleSnapshot response for symbol-contract verification."""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx

from pmjev.feeds.hyperliquid import candle_request, recent_trades_request


async def probe(coin: str) -> None:
    end = time.time()
    request = candle_request(coin, end - 3600, end)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post("https://api.hyperliquid.xyz/info", json=request)
        print("REQUEST", json.dumps(request))
        print("RESPONSE", response.status_code, response.text)
        trades_request = recent_trades_request(coin)
        trades_response = await client.post("https://api.hyperliquid.xyz/info", json=trades_request)
        print("TRADES_REQUEST", json.dumps(trades_request))
        print("TRADES_RESPONSE", trades_response.status_code, trades_response.text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coin", default="HYPE")
    args = parser.parse_args()
    asyncio.run(probe(args.coin))


if __name__ == "__main__":
    main()
