from __future__ import annotations

from pathlib import Path

import pytest

from pmjev.resolver import ResolvedWindow, Resolver
from pmjev.store import PredictionRecord, Store, TradeRecord


class FakeGamma:
    async def outcome(self, _slug: str) -> int | None:
        return 1


class FakeRedeemer:
    def __init__(self) -> None:
        self.conditions: list[str] = []

    async def redeem(self, *, condition_id: str) -> str:
        self.conditions.append(condition_id)
        return "0xtx"


@pytest.mark.asyncio
async def test_resolver_returns_newly_settled_windows_for_alerting(tmp_path: Path) -> None:
    store = Store(f"sqlite:///{tmp_path / 'resolver.sqlite'}")
    store.initialize()
    store.upsert_window(
        slug="btc-updown-5m-1",
        asset="btc",
        window_start=1,
        up_token="up",
        down_token="down",
        price_to_beat=100.0,
        status="open",
    )

    resolved, checked = await Resolver(store, FakeGamma()).resolve_pending_details()  # type: ignore[arg-type]

    assert resolved == [ResolvedWindow(slug="btc-updown-5m-1", outcome=1)]
    assert checked == 1
    store.close()


@pytest.mark.asyncio
async def test_resolver_settles_then_redeems_matched_live_position(tmp_path: Path) -> None:
    store = Store(f"sqlite:///{tmp_path / 'live-resolver.sqlite'}")
    store.initialize()
    store.upsert_window(
        slug="btc-updown-5m-1",
        asset="btc",
        window_start=1,
        up_token="up",
        down_token="down",
        condition_id="0xcondition",
        price_to_beat=100,
        status="open",
    )
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=150,
            ts=151,
            spot_chainlink=101,
            spot_binance=101,
            sigma_1s=0.001,
            up_bid=0.49,
            up_ask=0.50,
            down_ask=0.52,
            depth_ask_usd=100,
            p_jev=0.9,
            p_jev_mkt=None,
            p_gbm=0.8,
            jev_latency_ms=100,
            jev_error=None,
            state_json="{}",
        )
    )
    store.add_trade(
        TradeRecord(
            prediction_id=prediction_id,
            model="jev",
            mode="live",
            side="up",
            price=0.5,
            size=20,
            fee=0.1,
            order_id="order-1",
            execution_status="matched",
        )
    )
    redeemer = FakeRedeemer()

    await Resolver(
        store,
        FakeGamma(),  # type: ignore[arg-type]
        redeemer=redeemer,
    ).resolve_pending_details()

    assert redeemer.conditions == ["0xcondition"]
    window = store._connection.execute(
        "SELECT redeem_status, redeem_tx FROM windows WHERE slug = ?",
        ("btc-updown-5m-1",),
    ).fetchone()
    assert tuple(window) == ("redeemed", "0xtx")
    store.close()
