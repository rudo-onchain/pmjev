#!/usr/bin/env python3
"""Print raw Gamma responses for every configured asset slug."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from pmjev.assets import build_slug, load_assets


async def probe(assets_file: Path, timestamp: int | None) -> None:
    assets = load_assets(assets_file)
    async with httpx.AsyncClient(timeout=10) as client:
        for asset in assets:
            now = timestamp if timestamp is not None else int(time.time())
            window_start = now - (now % asset.window_seconds)
            slug = build_slug(asset, window_start)
            response = await client.get(
                "https://gamma-api.polymarket.com/events", params={"slug": slug}
            )
            print(
                json.dumps(
                    {
                        "asset": asset.name,
                        "slug": slug,
                        "status": response.status_code,
                        "raw": response.text,
                    }
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-file", type=Path, default=Path("assets.yaml"))
    parser.add_argument("--timestamp", type=int)
    args = parser.parse_args()
    asyncio.run(probe(args.assets_file, args.timestamp))


if __name__ == "__main__":
    main()
