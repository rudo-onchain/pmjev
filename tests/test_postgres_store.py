from __future__ import annotations

import re
from typing import Any

from pmjev.postgres_store import PostgresStore
from pmjev.store import PredictionRecord, TradeRecord


class FakeCursor:
    rowcount = 1

    def fetchone(self) -> dict[str, int]:
        return {"id": 7}


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, query: str, params: tuple[Any, ...]) -> FakeCursor:
        self.calls.append((query, params))
        return FakeCursor()


class ConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *_args: object) -> None:
        return None


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def connection(self) -> ConnectionContext:
        return ConnectionContext(self._connection)


class DashboardCursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class DashboardConnection(FakeConnection):
    def execute(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> DashboardCursor:
        self.calls.append((query, params))
        assert "AS window" not in query
        assert re.search(r"\bwindow\.", query) is None
        if "SELECT COUNT(*) AS value" in query:
            return DashboardCursor([{"value": 0}])
        return DashboardCursor()


def postgres_store_with_fake_connection() -> tuple[PostgresStore, FakeConnection]:
    connection = FakeConnection()
    store = object.__new__(PostgresStore)
    store._pool = FakePool(connection)  # type: ignore[assignment]
    return store, connection


def test_add_prediction_matches_postgres_placeholders() -> None:
    store, connection = postgres_store_with_fake_connection()
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=60,
            ts=61,
            spot_chainlink=101,
            spot_binance=101,
            sigma_1s=0.001,
            up_bid=0.49,
            up_ask=0.50,
            down_ask=0.52,
            depth_ask_usd=100,
            p_jev=0.9,
            p_jev_mkt=0.8,
            p_gbm=0.7,
            jev_latency_ms=100,
            jev_error=None,
            state_json='{"source":"test"}',
            p_deepseek=0.75,
            deepseek_latency_ms=800,
            deepseek_provider="DeepSeek",
        )
    )

    query, params = connection.calls[0]
    assert prediction_id == 7
    assert "public.predictions" in query
    assert "pmjev." not in query
    assert query.count("%s") == len(params) == 22
    assert params[10:13] == (0.9, 0.8, 0.7)
    assert params[-4:] == (0.75, 800, None, "DeepSeek")


def test_upsert_window_persists_dashboard_mark_metadata() -> None:
    store, connection = postgres_store_with_fake_connection()
    store.upsert_window(
        slug="btc-updown-5m-1",
        asset="btc",
        window_start=1,
        up_token="up",
        down_token="down",
        price_to_beat=100,
        status="open",
        window_seconds=300,
        fee_rate=0.07,
        fee_exponent=1,
    )

    query, params = connection.calls[0]
    assert "window_seconds, fee_rate, fee_exponent" in query
    assert query.count("%s") == len(params) == 11
    assert params[-3:] == (300, 0.07, 1)


def test_add_trade_matches_postgres_placeholders() -> None:
    store, connection = postgres_store_with_fake_connection()
    trade_id = store.add_trade(
        TradeRecord(
            prediction_id=7,
            model="jev",
            mode="paper",
            side="up",
            price=0.5,
            size=20,
            fee=0.1,
        )
    )

    query, params = connection.calls[0]
    assert trade_id == 7
    assert "public.trades" in query
    assert "public.predictions" in query
    assert "pmjev." not in query
    assert query.count("%s") == len(params) == 14
    assert params[-1] == 7


def test_refresh_dashboard_avoids_reserved_window_alias() -> None:
    connection = DashboardConnection()
    store = object.__new__(PostgresStore)
    store._pool = FakePool(connection)  # type: ignore[assignment]

    store.refresh_dashboard(mode="paper", starting_balance=100, now=1_000)

    assert any("public.dashboard_snapshots" in query for query, _ in connection.calls)
