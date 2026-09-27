from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from pmjev.alerts import (
    TelegramAlerts,
    entry_message,
    exit_message,
    settlement_message,
)
from pmjev.store import Store


def test_trade_messages_do_not_include_pnl() -> None:
    entry = entry_message(
        mode="paper",
        asset="btc",
        model="jev",
        side="up",
        price=0.68,
        stake=20.0,
        held_probability=0.90,
    )
    exited = exit_message(
        mode="paper",
        asset="btc",
        model="jev",
        side="up",
        entry_price=0.68,
        exit_price=0.30,
    )
    settled = settlement_message(
        mode="paper",
        asset="btc",
        model="jev",
        side="up",
        won=True,
    )

    assert entry == "🟢 IN | PAPER BTC JEV UP @0.68\n$20 | p=.90"
    assert exited == "🔴 EXIT | PAPER BTC JEV UP 0.68→0.30"
    assert settled == "✅ SET | PAPER BTC JEV UP WIN"
    trend = entry_message(
        mode="paper",
        asset="btc",
        model="trend_gbm",
        side="up",
        price=0.68,
        stake=20.0,
        held_probability=0.90,
    )
    assert trend == "🟢 IN | PAPER BTC TGBM UP @0.68\n$20 | p=.90"
    messages = (entry, exited, settled, trend)
    assert all("PnL" not in message and "Day" not in message for message in messages)


@pytest.mark.asyncio
async def test_telegram_delivery_runs_outside_caller_and_posts_plain_text(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    store = Store(f"sqlite:///{tmp_path / 'alerts.sqlite'}")
    store.initialize()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        alerts = TelegramAlerts(
            store=store,
            client=client,
            bot_token="test-token",
            chat_id="12345",
            message_thread_id=777,
        )
        task = asyncio.create_task(alerts.run())
        alerts.publish("🟢 IN | PAPER BTC JEV UP @0.68\n$20 | p=.90")
        await alerts.close()
        await task

    assert len(requests) == 1
    assert requests[0].url.path == "/bottest-token/sendMessage"
    assert json.loads(requests[0].content) == {
        "chat_id": "12345",
        "text": "🟢 IN | PAPER BTC JEV UP @0.68\n$20 | p=.90",
        "message_thread_id": 777,
    }
    store.close()


@pytest.mark.asyncio
async def test_telegram_failure_does_not_escape_worker(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "description": "failed"})

    store = Store(f"sqlite:///{tmp_path / 'failed-alert.sqlite'}")
    store.initialize()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        alerts = TelegramAlerts(
            store=store,
            client=client,
            bot_token="secret-token",
            chat_id="12345",
        )
        task = asyncio.create_task(alerts.run())
        alerts.publish("test")
        await alerts.close()
        await task

    assert "telegram alert failed status=500" in caplog.text
    assert "secret-token" not in caplog.text
    store.close()
