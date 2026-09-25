from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from pmjev.alerts import (
    SummaryPeriod,
    TelegramAlerts,
    due_summary_periods,
    entry_message,
    exit_message,
    settlement_message,
    summary_message,
)
from pmjev.store import Store

BANGKOK = ZoneInfo("Asia/Bangkok")


def test_trade_messages_use_two_compact_lines() -> None:
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
        pnl=-12.06,
        return_fraction=-0.603,
    )
    settled = settlement_message(
        mode="paper",
        asset="btc",
        model="jev",
        side="up",
        won=True,
        pnl=8.42,
        daily_pnl=34.15,
    )

    assert entry == "🟢 IN | PAPER BTC JEV UP @0.68\n$20 | p=.90"
    assert exited == "🔴 EXIT | PAPER BTC JEV UP 0.68→0.30\nPnL -$12.06 (-60%)"
    assert settled == "✅ SET | PAPER BTC JEV UP WIN\nPnL +$8.42 | Day +$34.15"
    assert all(len(message.splitlines()) == 2 for message in (entry, exited, settled))


def test_summary_messages_use_two_compact_lines() -> None:
    hourly = summary_message(
        mode="paper",
        icon="🕐",
        label="10-11h",
        totals={"jev": 18.0, "jev_mkt": -4.0, "gbm": 7.0},
    )
    daily = summary_message(
        mode="live",
        icon="📅",
        label="25 Sep",
        totals={"jev": 42.0, "jev_mkt": 19.0, "gbm": -9.0},
    )

    assert hourly == "🕐 PAPER 10-11h | JEV +$18 | MKT -$4\nGBM +$7 | Net +$21"
    assert daily == "📅 LIVE 25 Sep | JEV +$42 | MKT +$19\nGBM -$9 | Net +$52"


def test_summary_periods_are_due_at_bangkok_delivery_times() -> None:
    hourly = due_summary_periods(datetime(2026, 9, 25, 11, 2, tzinfo=BANGKOK))
    daily = due_summary_periods(datetime(2026, 9, 25, 7, 5, tzinfo=BANGKOK))

    assert hourly == [
        SummaryPeriod(
            key="hour:2026-09-25T10:00:00+07:00",
            icon="🕐",
            label="10-11h",
            start=datetime(2026, 9, 25, 10, 0, tzinfo=BANGKOK),
            end=datetime(2026, 9, 25, 11, 0, tzinfo=BANGKOK),
        )
    ]
    assert daily == [
        SummaryPeriod(
            key="day:2026-09-24",
            icon="📅",
            label="24 Sep",
            start=datetime(2026, 9, 24, 7, 0, tzinfo=BANGKOK),
            end=datetime(2026, 9, 25, 7, 0, tzinfo=BANGKOK),
        )
    ]


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
