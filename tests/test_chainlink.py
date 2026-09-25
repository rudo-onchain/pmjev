from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from pmjev.feeds.chainlink import (
    ChainlinkFeed,
    build_subscription,
    parse_chainlink_message,
    select_price_to_beat,
)
from pmjev.feeds.polybolt import (
    PolyBoltFeed,
    build_auth,
    build_twap_subscription,
    parse_polybolt_message,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_subscription_uses_verified_compact_string_filters() -> None:
    payload = build_subscription(["btc/usd", "hype/usd"], "crypto_prices_twap_sixty")
    assert payload == {
        "action": "subscribe",
        "subscriptions": [
            {
                "topic": "crypto_prices_twap_sixty",
                "type": "update",
                "filters": '{"symbol":"btc/usd"}',
            },
            {
                "topic": "crypto_prices_twap_sixty",
                "type": "update",
                "filters": '{"symbol":"hype/usd"}',
            },
        ],
    }


def test_parse_twap_subscription_snapshot() -> None:
    raw = (FIXTURES / "chainlink_twap_snapshot.json").read_text(encoding="utf-8")
    ticks = parse_chainlink_message(raw)
    assert len(ticks) == 2
    assert ticks[0].symbol == "btc/usd"
    assert ticks[0].timestamp == pytest.approx(1_790_231_122)
    assert ticks[0].price == pytest.approx(84_111.17591825358)


def test_select_price_to_beat_uses_exact_boundary_tick() -> None:
    raw = (FIXTURES / "chainlink_twap_snapshot.json").read_text(encoding="utf-8")
    tick = select_price_to_beat(parse_chainlink_message(raw), 1_790_231_123)
    assert tick is not None
    assert tick.timestamp == 1_790_231_123


def test_empty_and_pong_frames_are_ignored() -> None:
    assert parse_chainlink_message("") == []
    assert parse_chainlink_message("PONG") == []


class FakeRtdsWebSocket:
    def __init__(self) -> None:
        self.frames: asyncio.Queue[str] = asyncio.Queue()

    async def __aenter__(self) -> FakeRtdsWebSocket:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def send(self, raw: str) -> None:
        if raw == "PING":
            return
        subscription: dict[str, Any] = json.loads(raw)
        first = subscription["subscriptions"][0]
        symbol = json.loads(first["filters"])["symbol"]
        self.frames.put_nowait(
            json.dumps(
                {
                    "type": "update",
                    "payload": {"symbol": symbol, "timestamp": 100_000, "value": 123.0},
                }
            )
        )

    def __aiter__(self) -> FakeRtdsWebSocket:
        return self

    async def __anext__(self) -> str:
        return await self.frames.get()


@pytest.mark.asyncio
async def test_feed_uses_one_connection_per_symbol_for_live_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sockets: list[FakeRtdsWebSocket] = []

    def connect(_url: str) -> FakeRtdsWebSocket:
        socket = FakeRtdsWebSocket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr("pmjev.feeds.chainlink.websockets.connect", connect)
    feed = ChainlinkFeed(
        "wss://rtds.test",
        ["btc/usd", "eth/usd"],
        "crypto_prices_twap_sixty",
    )
    task = asyncio.create_task(feed.run())
    try:
        for _ in range(20):
            if feed.latest("btc/usd") is not None and feed.latest("eth/usd") is not None:
                break
            await asyncio.sleep(0)
        assert feed.latest("btc/usd") is not None
        assert feed.latest("eth/usd") is not None
        assert len(sockets) == 2
    finally:
        feed.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_polybolt_frames_and_twap_parser() -> None:
    assert build_auth(api_key="key", secret="secret", passphrase="pass") == {
        "op": "auth",
        "rid": "auth-1",
        "auth": {"apiKey": "key", "secret": "secret", "passphrase": "pass"},
    }
    assert build_twap_subscription(["btc/usd", "SOL/USD"])["subscriptions"] == [
        {
            "channel": "price.crypto.twap",
            "filter": {"symbol": "btcusd", "window_seconds": 60},
        },
        {
            "channel": "price.crypto.twap",
            "filter": {"symbol": "solusd", "window_seconds": 60},
        },
    ]
    ticks = parse_polybolt_message(
        json.dumps(
            {
                "topic": "prices.crypto.twap",
                "type": "subscribe",
                "payload": {
                    "symbol": "btcusd",
                    "windowSeconds": 60,
                    "data": [
                        {"timestamp": 1_790_000_000_000, "value": "84111.125"},
                        {"timestamp": 1_790_000_001_000, "value": "84112.25"},
                    ],
                },
            }
        )
    )
    assert [tick.timestamp for tick in ticks] == [1_790_000_000, 1_790_000_001]
    assert ticks[-1].price == pytest.approx(84_112.25)


class FakePolyBoltWebSocket:
    def __init__(self) -> None:
        self.frames: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []

    async def __aenter__(self) -> FakePolyBoltWebSocket:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def send(self, raw: str) -> None:
        frame: dict[str, Any] = json.loads(raw)
        self.sent.append(frame)
        if frame["op"] == "auth":
            self.frames.put_nowait(json.dumps({"op": "authed", "rid": frame["rid"]}))
        elif frame["op"] == "subscribe":
            for subscription in frame["subscriptions"]:
                symbol = subscription["filter"]["symbol"]
                self.frames.put_nowait(
                    json.dumps(
                        {
                            "topic": "prices.crypto.twap",
                            "type": "update",
                            "payload": {
                                "symbol": symbol,
                                "timestamp": 100_000,
                                "value": "123.45",
                                "windowSeconds": 60,
                            },
                        }
                    )
                )

    async def recv(self) -> str:
        return await self.frames.get()

    def __aiter__(self) -> FakePolyBoltWebSocket:
        return self

    async def __anext__(self) -> str:
        return await self.frames.get()


@pytest.mark.asyncio
async def test_polybolt_uses_one_authenticated_connection_for_all_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sockets: list[FakePolyBoltWebSocket] = []

    def connect(_url: str) -> FakePolyBoltWebSocket:
        socket = FakePolyBoltWebSocket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr("pmjev.feeds.polybolt.websockets.connect", connect)
    feed = PolyBoltFeed(
        "wss://polybolt.test",
        ["btc/usd", "sol/usd"],
        api_key="key",
        secret="secret",
        passphrase="pass",
    )
    task = asyncio.create_task(feed.run())
    try:
        for _ in range(20):
            if feed.latest("btc/usd") and feed.latest("sol/usd"):
                break
            await asyncio.sleep(0)
        assert feed.latest("btc/usd") is not None
        assert feed.latest("sol/usd") is not None
        assert len(sockets) == 1
        assert [frame["op"] for frame in sockets[0].sent] == ["auth", "subscribe"]
        assert len(sockets[0].sent[1]["subscriptions"]) == 2
    finally:
        feed.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
