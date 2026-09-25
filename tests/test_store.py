from __future__ import annotations

from pathlib import Path

import pytest

from pmjev.report import render_report
from pmjev.store import PredictionRecord, Store, TradeRecord


def test_store_initializes_exact_tables(tmp_path: Path) -> None:
    store = Store(f"sqlite:///{tmp_path / 'test.sqlite'}")
    store.initialize()
    names = {
        row[0]
        for row in store._connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"windows", "predictions", "trades"} <= names
    prediction_columns = {
        row[1] for row in store._connection.execute("PRAGMA table_info(predictions)")
    }
    assert "p_trend_gbm" in prediction_columns
    store.close()


def test_settle_trades_fills_pnl(tmp_path: Path) -> None:
    store = Store(f"sqlite:///{tmp_path / 'settle.sqlite'}")
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
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=60,
            ts=61.0,
            spot_chainlink=101.0,
            spot_binance=101.0,
            sigma_1s=0.001,
            up_bid=0.59,
            up_ask=0.60,
            down_ask=0.42,
            depth_ask_usd=20.0,
            p_jev=0.7,
            p_jev_mkt=0.65,
            p_gbm=0.6,
            p_trend_gbm=0.62,
            jev_latency_ms=100.0,
            jev_error=None,
            state_json="{}",
        )
    )
    store.add_trade(
        TradeRecord(
            prediction_id=prediction_id,
            model="jev",
            mode="paper",
            side="up",
            price=0.60,
            size=1.0,
            fee=0.01,
            fill_price=0.60,
        )
    )
    store.mark_resolved("btc-updown-5m-1", 1, None)
    store.settle_trades("btc-updown-5m-1", 1)
    trade = store.resolved_trades()[0]
    assert trade["pnl"] == pytest.approx(0.39)
    report = render_report(store)
    assert "BTC @ t+60s" in report
    assert "trend_gbm" in report
    assert "95% paired bootstrap CI" in report
    assert report.count("n=0 p=- y=-") == 9
    store.close()


def test_report_uses_stored_pnl_for_early_closed_trade(tmp_path: Path) -> None:
    store = Store(f"sqlite:///{tmp_path / 'closed-report.sqlite'}")
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
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=60,
            ts=61.0,
            spot_chainlink=101.0,
            spot_binance=101.0,
            sigma_1s=0.001,
            up_bid=0.67,
            up_ask=0.68,
            down_ask=0.34,
            depth_ask_usd=20.0,
            p_jev=0.9,
            p_jev_mkt=None,
            p_gbm=0.8,
            jev_latency_ms=100.0,
            jev_error=None,
            state_json="{}",
        )
    )
    store.add_trade(
        TradeRecord(
            prediction_id=prediction_id,
            model="jev",
            mode="paper",
            side="up",
            price=0.68,
            size=10.0,
            fee=0.15,
            fill_price=0.68,
            pnl=-4.00,
            exit_price=0.30,
            exit_fee=0.15,
        )
    )
    store.mark_resolved("btc-updown-5m-1", 1, None)
    store.settle_trades("btc-updown-5m-1", 1)

    report = render_report(store)
    assert "jev: n=1 pnl=-4.0000" in report
    store.close()


def test_report_pnl_includes_trend_gbm_trades(tmp_path: Path) -> None:
    store = Store(f"sqlite:///{tmp_path / 'trend-report.sqlite'}")
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
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=240,
            ts=241.0,
            spot_chainlink=101.0,
            spot_binance=101.0,
            sigma_1s=0.001,
            up_bid=0.67,
            up_ask=0.68,
            down_ask=0.34,
            depth_ask_usd=20.0,
            p_jev=None,
            p_jev_mkt=None,
            p_gbm=0.8,
            p_trend_gbm=0.9,
            jev_latency_ms=None,
            jev_error=None,
            state_json="{}",
        )
    )
    store.add_trade(
        TradeRecord(
            prediction_id=prediction_id,
            model="trend_gbm",
            mode="paper",
            side="up",
            price=0.68,
            size=10.0,
            fee=0.15,
            fill_price=0.68,
        )
    )
    store.mark_resolved("btc-updown-5m-1", 1, None)
    store.settle_trades("btc-updown-5m-1", 1)

    report = render_report(store)
    assert "trend_gbm: n=1 pnl=" in report
    store.close()


def test_pnl_summary_uses_trade_close_time(tmp_path: Path) -> None:
    store = Store(f"sqlite:///{tmp_path / 'summary.sqlite'}")
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
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=60,
            ts=10.0,
            spot_chainlink=101.0,
            spot_binance=101.0,
            sigma_1s=0.001,
            up_bid=0.59,
            up_ask=0.60,
            down_ask=0.42,
            depth_ask_usd=20.0,
            p_jev=0.7,
            p_jev_mkt=0.65,
            p_gbm=0.6,
            jev_latency_ms=100.0,
            jev_error=None,
            state_json="{}",
        )
    )
    store.add_trade(
        TradeRecord(
            prediction_id=prediction_id,
            model="jev",
            mode="paper",
            side="up",
            price=0.60,
            size=1.0,
            fee=0.01,
            pnl=5.0,
            closed_at=200.0,
        )
    )
    store.add_trade(
        TradeRecord(
            prediction_id=prediction_id,
            model="gbm",
            mode="paper",
            side="up",
            price=0.60,
            size=1.0,
            fee=0.01,
            pnl=-2.0,
            closed_at=300.0,
        )
    )

    assert store.pnl_by_model(100.0, 250.0) == {"jev": pytest.approx(5.0)}
    assert store.pnl_by_model(250.0, 350.0) == {"gbm": pytest.approx(-2.0)}
    store.close()
