"""High-conviction stake tier: bigger stake on strong edges, never on naive_spot."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmjev.config import Settings
from pmjev.executor import AttemptContext, Candidate, Executor, StakeTier
from pmjev.store import PredictionRecord, Store

SLUG = "btc-updown-5m-2000"
TIER = StakeTier(stake_usd=10, min_edge=0.05, min_probability=0.55)


def make_store(tmp_path: Path) -> tuple[Store, int]:
    store = Store(f"sqlite:///{tmp_path / 'tier.sqlite'}")
    store.initialize()
    store.upsert_window(
        slug=SLUG,
        asset="btc",
        window_start=2000,
        up_token="up",
        down_token="down",
        price_to_beat=100.0,
        status="open",
    )
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug=SLUG,
            t_elapsed=150,
            ts=1.0,
            spot_chainlink=100.5,
            spot_binance=100.5,
            sigma_1s=0.001,
            up_bid=0.49,
            up_ask=0.50,
            down_ask=0.51,
            depth_ask_usd=100.0,
            p_jev=None,
            p_jev_mkt=None,
            p_gbm=0.7,
            jev_latency_ms=None,
            jev_error=None,
            state_json="{}",
        )
    )
    return store, prediction_id


def run(
    tmp_path: Path,
    candidate: Candidate,
    *,
    tier: StakeTier | None = TIER,
    up_levels: tuple[tuple[float, float], ...] = ((0.50, 1000.0),),
):
    store, prediction_id = make_store(tmp_path)
    trade = Executor("paper", store, 0.018, stake_tier=tier).execute(
        slug=SLUG,
        prediction_id=prediction_id,
        candidate=candidate,
        up_ask=0.50,
        down_ask=0.51,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        up_levels=up_levels,
        attempt=AttemptContext(0.50, 0.51, snapshot_ts=1.0, decided_at=1.1),
    )
    return store, trade


def test_strong_edge_uses_high_stake(tmp_path: Path) -> None:
    # edge = 0.70 - 0.50 - fee(0.50) ~= 0.18
    store, trade = run(tmp_path, Candidate("trend_gbm", 0.70))
    assert trade is not None and trade.side == "up"
    assert trade.price * trade.size == pytest.approx(10)
    assert store.entry_attempts()[0]["stake_usd"] == pytest.approx(10)


def test_small_edge_keeps_base_stake(tmp_path: Path) -> None:
    # edge = 0.56 - 0.50 - 0.0175 ~= 0.0425: clears EDGE 0.03 but not the 0.05 tier.
    store, trade = run(tmp_path, Candidate("trend_gbm", 0.56))
    assert trade is not None
    assert trade.price * trade.size == pytest.approx(5)
    assert store.entry_attempts()[0]["stake_usd"] == pytest.approx(5)


def test_low_held_probability_keeps_base_stake(tmp_path: Path) -> None:
    tier = StakeTier(stake_usd=10, min_edge=0.05, min_probability=0.80)
    _, trade = run(tmp_path, Candidate("trend_gbm", 0.70), tier=tier)
    assert trade is not None
    assert trade.price * trade.size == pytest.approx(5)


def test_tier_respects_model_allowlist(tmp_path: Path) -> None:
    tier = StakeTier(stake_usd=10, min_edge=0.05, models=frozenset({"jev"}))
    _, trade = run(tmp_path, Candidate("trend_gbm", 0.70), tier=tier)
    assert trade is not None
    assert trade.price * trade.size == pytest.approx(5)


def test_rule_based_never_scales(tmp_path: Path) -> None:
    candidate = Candidate(
        "naive_spot", 0.99, requested_side="up", rule_based=True, max_price=0.90
    )
    _, trade = run(tmp_path, candidate)
    assert trade is not None
    assert trade.price * trade.size == pytest.approx(5)


def test_thin_book_falls_back_to_base_stake(tmp_path: Path) -> None:
    # $7.50 available at 0.50: enough for $5, not for $10.
    store, trade = run(
        tmp_path, Candidate("trend_gbm", 0.70), up_levels=((0.50, 15.0), (0.95, 1000.0))
    )
    assert trade is not None
    assert trade.price * trade.size == pytest.approx(5)
    assert store.entry_attempts()[0]["stake_usd"] == pytest.approx(5)


def test_no_tier_keeps_base_stake(tmp_path: Path) -> None:
    _, trade = run(tmp_path, Candidate("trend_gbm", 0.70), tier=None)
    assert trade is not None
    assert trade.price * trade.size == pytest.approx(5)


def test_settings_parse_high_stake_models() -> None:
    settings = Settings(_env_file=None, high_stake_usd=10, high_stake_models=" JEV, trend_gbm ")
    assert settings.high_stake_model_names == frozenset({"jev", "trend_gbm"})
    assert Settings(_env_file=None, high_stake_models="").high_stake_model_names is None
    assert Settings(_env_file=None, high_stake_usd="").high_stake_usd is None
