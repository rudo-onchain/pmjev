from __future__ import annotations

import time
from pathlib import Path

from pmjev.risk import LiveRiskGuard, RiskLimits
from pmjev.store import PredictionRecord, Store, TradeRecord


def risk_store(tmp_path: Path) -> tuple[Store, int]:
    store = Store(f"sqlite:///{tmp_path / 'risk.sqlite'}")
    store.initialize()
    store.upsert_window(
        slug="btc-updown-5m-1",
        asset="btc",
        window_start=1,
        up_token="up",
        down_token="down",
        price_to_beat=100,
        status="open",
    )
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=150,
            ts=time.time(),
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
    return store, prediction_id


def test_live_risk_blocks_portfolio_exposure_before_order(tmp_path: Path) -> None:
    store, prediction_id = risk_store(tmp_path)
    store.add_trade(
        TradeRecord(
            prediction_id=prediction_id,
            model="jev",
            mode="live",
            side="up",
            price=0.5,
            size=50,
            fee=0,
        )
    )
    guard = LiveRiskGuard(
        store,
        RiskLimits(max_notional_usd=30, max_trade_usd=10, daily_loss_limit_usd=25),
        stop_file=tmp_path / "STOP",
    )
    now = time.time()
    reason = guard.block_reason(
        now=now,
        requested_notional=10,
        reference_timestamp=now,
    )
    assert reason is not None and "portfolio exposure $35.00" in reason


def test_live_risk_drawdown_latches_until_manual_reset(tmp_path: Path) -> None:
    store, prediction_id = risk_store(tmp_path)
    store.add_trade(
        TradeRecord(
            prediction_id=prediction_id,
            model="jev",
            mode="live",
            side="up",
            price=0.5,
            size=20,
            fee=0,
            pnl=-100,
            closed_at=time.time(),
        )
    )
    guard = LiveRiskGuard(
        store,
        RiskLimits(
            max_notional_usd=30,
            max_trade_usd=10,
            daily_loss_limit_usd=1_000,
            max_drawdown_usd=100,
        ),
        stop_file=tmp_path / "STOP",
    )
    now = time.time()
    reason = guard.block_reason(
        now=now,
        requested_notional=10,
        reference_timestamp=now,
    )
    assert reason is not None and "permanent limit" in reason
    assert guard.latched_reason == reason


def test_live_risk_blocks_high_recent_jev_error_rate(tmp_path: Path) -> None:
    store, _ = risk_store(tmp_path)
    store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=180,
            ts=time.time(),
            spot_chainlink=101,
            spot_binance=101,
            sigma_1s=0.001,
            up_bid=0.49,
            up_ask=0.50,
            down_ask=0.52,
            depth_ask_usd=100,
            p_jev=None,
            p_jev_mkt=None,
            p_gbm=0.8,
            jev_latency_ms=1_500,
            jev_error="blind: timeout",
            state_json="{}",
        )
    )
    guard = LiveRiskGuard(
        store,
        RiskLimits(max_notional_usd=30, max_trade_usd=10, daily_loss_limit_usd=25),
        stop_file=tmp_path / "STOP",
    )
    now = time.time()
    reason = guard.block_reason(
        now=now,
        requested_notional=10,
        reference_timestamp=now,
    )
    assert reason is not None and "Jev error rate 50.0%" in reason
