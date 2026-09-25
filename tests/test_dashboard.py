from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pmjev.dashboard import build_dashboard_snapshot


def trade_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 1,
        "model": "jev",
        "side": "up",
        "price": 0.5,
        "size": 20.0,
        "fee": 0.1,
        "pnl": None,
        "exit_price": None,
        "closed_at": None,
        "created_at": datetime.fromtimestamp(900, tz=UTC),
        "asset": "btc",
        "window_start": 900,
        "window_seconds": 300,
        "status": "open",
        "outcome": None,
        "fee_rate": 0.0,
        "fee_exponent": 1,
        "up_bid": 0.6,
        "down_bid": 0.4,
        "market_data_at": 995.0,
    }
    row.update(overrides)
    return row


def test_dashboard_snapshot_marks_open_positions_at_current_bid() -> None:
    snapshot = build_dashboard_snapshot(
        [trade_row()],
        assets=["btc", "sol"],
        mode="paper",
        starting_balance=100,
        now=1_000,
    )

    assert snapshot["mode"] == "paper"
    assert snapshot["assets"] == ["BTC", "SOL"]
    assert snapshot["realized_pnl"] == 0
    assert snapshot["unrealized_pnl"] == pytest.approx(1.9)
    assert snapshot["open_exposure"] == pytest.approx(10.1)
    assert snapshot["available_balance"] == pytest.approx(89.9)
    assert snapshot["portfolio_equity"] == pytest.approx(101.9)
    assert snapshot["snapshot_updated_at"] == "1970-01-01T00:16:40Z"
    assert snapshot["market_data_at"] == "1970-01-01T00:16:35Z"
    assert snapshot["last_trade_at"] == "1970-01-01T00:15:00Z"
    assert snapshot["open_positions"][0] == {
        "id": "1",
        "asset": "BTC",
        "model": "JEV",
        "side": "UP",
        "entry_price": 0.5,
        "current_bid": 0.6,
        "size_usd": 10.0,
        "unrealized_pnl": pytest.approx(1.9),
        "market_end_at": "1970-01-01T00:20:00Z",
        "status": "open",
    }


def test_dashboard_snapshot_separates_resolved_and_exited_activity() -> None:
    rows = [
        trade_row(
            id=1,
            pnl=9.9,
            closed_at=1_200.0,
            outcome=1,
            status="resolved",
        ),
        trade_row(
            id=2,
            model="gbm",
            pnl=-2.1,
            exit_price=0.4,
            closed_at=1_100.0,
        ),
    ]

    snapshot = build_dashboard_snapshot(
        rows,
        assets=["btc"],
        mode="live",
        starting_balance=100,
        now=1_300,
    )

    closed = [event for event in snapshot["recent_activity"] if event["type"] != "opened"]
    assert closed[0]["type"] == "resolved"
    assert closed[0]["outcome"] == "won"
    assert closed[0]["price"] == 1.0
    assert closed[1]["type"] == "exited"
    assert closed[1]["price"] == 0.4
    assert snapshot["realized_pnl"] == pytest.approx(7.8)
    assert snapshot["unrealized_pnl"] == 0
    assert snapshot["last_trade_at"] == "1970-01-01T00:20:00Z"


def test_dashboard_snapshot_uses_global_market_time_without_open_positions() -> None:
    snapshot = build_dashboard_snapshot(
        [trade_row(pnl=1.0, closed_at=1_100.0)],
        assets=["btc"],
        mode="paper",
        starting_balance=100,
        now=1_300,
        market_data_at=1_250,
    )

    assert snapshot["open_positions"] == []
    assert snapshot["market_data_at"] == "1970-01-01T00:20:50Z"


def test_dashboard_snapshot_uses_oldest_open_position_market_time() -> None:
    snapshot = build_dashboard_snapshot(
        [trade_row(id=1, market_data_at=990), trade_row(id=2, market_data_at=970)],
        assets=["btc"],
        mode="paper",
        starting_balance=100,
        now=1_000,
        market_data_at=999,
    )

    assert snapshot["market_data_at"] == "1970-01-01T00:16:10Z"


def test_dashboard_snapshot_ignores_awaiting_resolution_market_time() -> None:
    snapshot = build_dashboard_snapshot(
        [
            trade_row(id=1, window_start=600, market_data_at=700),
            trade_row(id=2, window_start=900, market_data_at=990),
        ],
        assets=["btc"],
        mode="paper",
        starting_balance=100,
        now=1_000,
        market_data_at=999,
    )

    assert snapshot["open_positions"][0]["status"] == "awaiting_resolution"
    assert snapshot["market_data_at"] == "1970-01-01T00:16:30Z"


def test_dashboard_snapshot_uses_market_fee_for_unrealized_pnl() -> None:
    snapshot = build_dashboard_snapshot(
        [trade_row(fee_rate=0.07)],
        assets=["btc"],
        mode="paper",
        starting_balance=100,
        now=1_000,
    )

    expected_exit_fee = 0.07 * (0.6 * 0.4) * 20
    assert snapshot["unrealized_pnl"] == pytest.approx(2 - 0.1 - expected_exit_fee)


@pytest.mark.parametrize("mode", ["shadow", "invalid"])
def test_dashboard_snapshot_rejects_unsupported_modes(mode: str) -> None:
    with pytest.raises(ValueError, match="paper or live"):
        build_dashboard_snapshot(
            [], assets=[], mode=mode, starting_balance=100, now=1_000
        )
