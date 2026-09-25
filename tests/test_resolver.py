from __future__ import annotations

from pathlib import Path

import pytest

from pmjev.resolver import ResolvedWindow, Resolver
from pmjev.store import Store


class FakeGamma:
    async def outcome(self, _slug: str) -> int | None:
        return 1


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
