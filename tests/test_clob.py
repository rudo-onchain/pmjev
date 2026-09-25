from __future__ import annotations

import httpx
import pytest

from pmjev.market.clob import ClobClient


def _client(books: dict[str, dict[str, object]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        token_id = request.url.params["token_id"]
        return httpx.Response(200, json=books[token_id])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_snapshot_exposes_best_bid_for_each_outcome() -> None:
    client = _client(
        {
            "up": {
                "bids": [{"price": "0.28", "size": "4"}, {"price": "0.30", "size": "2"}],
                "asks": [{"price": "0.32", "size": "3"}],
            },
            "down": {
                "bids": [{"price": "0.67", "size": "5"}],
                "asks": [{"price": "0.70", "size": "1"}],
            },
        }
    )
    try:
        snapshot = await ClobClient(client, "https://clob.test").snapshot("up", "down")
    finally:
        await client.aclose()

    assert snapshot.up_bid == pytest.approx(0.30)
    assert snapshot.down_bid == pytest.approx(0.67)


@pytest.mark.asyncio
async def test_snapshot_keeps_checkpoint_usable_when_an_exit_bid_is_missing() -> None:
    client = _client(
        {
            "up": {"bids": [], "asks": [{"price": "0.32", "size": "3"}]},
            "down": {"bids": [], "asks": [{"price": "0.70", "size": "1"}]},
        }
    )
    try:
        snapshot = await ClobClient(client, "https://clob.test").snapshot("up", "down")
    finally:
        await client.aclose()

    assert snapshot.up_bid is None
    assert snapshot.down_bid is None

