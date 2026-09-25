from __future__ import annotations

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
        )
    )

    query, params = connection.calls[0]
    assert prediction_id == 7
    assert query.count("%s") == len(params) == 18
    assert params[10:13] == (0.9, 0.8, 0.7)


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
    assert query.count("%s") == len(params) == 14
    assert params[-1] == 7
