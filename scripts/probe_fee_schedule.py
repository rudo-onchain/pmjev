#!/usr/bin/env python3
"""Print raw Gamma and CLOB fee-rate responses for a concrete market."""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx


async def probe(slug: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        gamma = await client.get("https://gamma-api.polymarket.com/events", params={"slug": slug})
        print("GAMMA", gamma.status_code, gamma.text)
        gamma.raise_for_status()
        events = gamma.json()
        if not events:
            return
        market = events[0].get("markets", [events[0]])[0]
        raw_tokens = market.get("clobTokenIds", [])
        token_ids = json.loads(raw_tokens) if isinstance(raw_tokens, str) else raw_tokens
        print("GAMMA_FEE_SCHEDULE", json.dumps(market.get("feeSchedule"), sort_keys=True))
        for token_id in token_ids:
            # The endpoint currently reports base_fee=1000. Runtime simulation uses
            # Gamma's explicit feeSchedule, which matches Polymarket's published formula.
            response = await client.get(
                "https://clob.polymarket.com/fee-rate", params={"token_id": token_id}
            )
            print("FEE_RATE", token_id, response.status_code, response.text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug", help="A concrete market slug, including its timestamp")
    args = parser.parse_args()
    asyncio.run(probe(args.slug))


if __name__ == "__main__":
    main()
