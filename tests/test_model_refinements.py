"""Tests for market anchoring, the naive_spot control, slippage, and hold_pnl."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from pmjev.config import Settings
from pmjev.executor import Candidate, Executor, anchor_to_market, fee_per_share
from pmjev.features import Kline10s
from pmjev.main import checkpoint_candidates, naive_spot_side
from pmjev.predictors.deepseek_direct import (
    SYSTEM_PROMPT,
    DeepSeekDirectPredictor,
    DirectMarketContext,
)
from pmjev.report import render_trade_summary
from pmjev.store import PredictionRecord, Store

SLUG = "btc-updown-5m-1"


def make_store(tmp_path: Path) -> Store:
    store = Store(f"sqlite:///{tmp_path / 'refinements.sqlite'}")
    store.initialize()
    store.upsert_window(
        slug=SLUG,
        asset="btc",
        window_start=1,
        up_token="up",
        down_token="down",
        price_to_beat=100.0,
        status="open",
    )
    return store


def add_checkpoint(store: Store, elapsed: int) -> int:
    return store.add_prediction(
        PredictionRecord(
            slug=SLUG,
            t_elapsed=elapsed,
            ts=float(elapsed),
            spot_chainlink=101.0,
            spot_binance=101.0,
            sigma_1s=0.001,
            up_bid=0.68,
            up_ask=0.70,
            down_ask=0.32,
            depth_ask_usd=20.0,
            p_jev=None,
            p_jev_mkt=None,
            p_gbm=0.8,
            jev_latency_ms=None,
            jev_error=None,
            state_json="{}",
        )
    )


# --- market anchoring -------------------------------------------------------


def test_anchor_shrinks_toward_mid_and_is_bounded() -> None:
    assert anchor_to_market(0.90, 0.70, 0.5) == pytest.approx(0.80)
    assert anchor_to_market(0.10, 0.70, 0.5) == pytest.approx(0.40)
    assert anchor_to_market(0.90, None, 0.5) == pytest.approx(0.90)
    assert anchor_to_market(0.90, 0.70, 1.0) == pytest.approx(0.90)
    assert anchor_to_market(0.90, 0.70, 0.0) == pytest.approx(0.70)
    with pytest.raises(ValueError):
        anchor_to_market(0.5, 0.5, 1.5)


def test_candidates_carry_anchored_and_raw_probabilities() -> None:
    exits, entries = checkpoint_candidates(
        p_gbm=0.90,
        p_jev=None,
        p_jev_mkt=None,
        gbm_trade=True,
        p_trend_gbm=0.60,
        trend_gbm_trade=False,
        market_mid=0.70,
        shrink_k=0.5,
    )
    gbm = next(candidate for candidate in exits if candidate.model == "gbm")
    assert gbm.probability_up == pytest.approx(0.80)
    assert gbm.raw_probability_up == pytest.approx(0.90)
    assert [candidate.model for candidate in entries] == ["gbm"]


def test_gap_guard_uses_raw_probability(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = add_checkpoint(store, 150)
    # Anchored p (0.80) is within 0.15 of mid, the raw p (0.95) is not.
    trade = Executor("paper", store, 0.018).execute(
        slug=SLUG,
        prediction_id=prediction_id,
        candidate=Candidate("gbm", 0.80, raw_probability_up=0.95),
        up_ask=0.70,
        down_ask=0.32,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        market_probability_up=0.69,
        max_model_market_gap=0.15,
    )
    assert trade is None


# --- naive_spot control ------------------------------------------------------


def test_naive_spot_side_follows_spot_inside_ask_band() -> None:
    kwargs = {"price_to_beat": 100.0, "min_ask": 0.6, "max_ask": 0.9}
    assert naive_spot_side(spot=101.0, up_ask=0.75, down_ask=0.27, **kwargs) == "up"
    assert naive_spot_side(spot=99.0, up_ask=0.25, down_ask=0.77, **kwargs) == "down"
    assert naive_spot_side(spot=100.0, up_ask=0.65, down_ask=0.37, **kwargs) == "up"
    assert naive_spot_side(spot=101.0, up_ask=0.95, down_ask=0.07, **kwargs) is None
    assert naive_spot_side(spot=101.0, up_ask=0.55, down_ask=0.47, **kwargs) is None
    assert naive_spot_side(spot=101.0, up_ask=None, down_ask=0.27, **kwargs) is None


def test_naive_spot_is_entry_only_and_respects_allow_entry() -> None:
    exits, entries = checkpoint_candidates(
        p_gbm=0.5,
        p_jev=None,
        p_jev_mkt=None,
        gbm_trade=False,
        p_trend_gbm=0.5,
        trend_gbm_trade=False,
        market_mid=0.72,
        naive_side="up",
        naive_trade=True,
    )
    assert [candidate.model for candidate in entries] == ["naive_spot"]
    assert entries[0].rule_based and entries[0].requested_side == "up"
    assert "naive_spot" not in {candidate.model for candidate in exits}
    _, blocked = checkpoint_candidates(
        p_gbm=0.5,
        p_jev=None,
        p_jev_mkt=None,
        gbm_trade=False,
        p_trend_gbm=0.5,
        trend_gbm_trade=False,
        naive_side="up",
        naive_trade=True,
        allow_entry=False,
    )
    assert blocked == []


def test_naive_spot_trades_without_edge_and_never_exits(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = add_checkpoint(store, 150)
    executor = Executor("paper", store, 0.018)
    candidate = Candidate("naive_spot", 0.69, requested_side="up", rule_based=True)
    trade = executor.execute(
        slug=SLUG,
        prediction_id=entry,
        candidate=candidate,
        up_ask=0.70,
        down_ask=0.32,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        spot=101.0,
        feature_spot=101.0,
        price_to_beat=100.0,
        market_probability_up=0.69,
        max_model_market_gap=0.15,
    )
    assert trade is not None and trade.side == "up"
    later = add_checkpoint(store, 180)
    assert (
        executor.evaluate_exit(
            slug=SLUG,
            prediction_id=later,
            candidate=candidate,
            up_bid=0.10,
            down_bid=0.88,
            fee_rate=0.07,
            spot=99.0,
            price_to_beat=100.0,
        )
        is None
    )


def test_naive_spot_still_blocked_when_feeds_straddle_target(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = add_checkpoint(store, 150)
    trade = Executor("paper", store, 0.018).execute(
        slug=SLUG,
        prediction_id=entry,
        candidate=Candidate("naive_spot", 0.69, requested_side="up", rule_based=True),
        up_ask=0.70,
        down_ask=0.32,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        spot=100.5,
        feature_spot=99.5,
        price_to_beat=100.0,
    )
    assert trade is None


# --- paper slippage and exit switch -----------------------------------------


def test_paper_slippage_worsens_entry_and_exit_prices(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = add_checkpoint(store, 150)
    executor = Executor("paper", store, 0.018, paper_slippage_ticks=1)
    trade = executor.execute(
        slug=SLUG,
        prediction_id=entry,
        candidate=Candidate("gbm", 0.90),
        up_ask=0.70,
        down_ask=0.32,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
    )
    assert trade is not None
    assert trade.price == pytest.approx(0.71)
    assert trade.fee == pytest.approx(fee_per_share(0.71, 0.07) * trade.size)
    later = add_checkpoint(store, 180)
    closed = executor.evaluate_exit(
        slug=SLUG,
        prediction_id=later,
        candidate=Candidate("gbm", 0.20),
        up_bid=0.40,
        down_bid=0.58,
        fee_rate=0.07,
    )
    assert closed is not None
    assert closed.exit_price == pytest.approx(0.39)


def test_paper_early_exits_can_be_disabled(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = add_checkpoint(store, 150)
    executor = Executor("paper", store, 0.018, paper_early_exits=False)
    assert (
        executor.execute(
            slug=SLUG,
            prediction_id=entry,
            candidate=Candidate("gbm", 0.90),
            up_ask=0.70,
            down_ask=0.32,
            edge=0.03,
            fee_rate=0.07,
            stake_usd=5,
        )
        is not None
    )
    later = add_checkpoint(store, 180)
    assert (
        executor.evaluate_exit(
            slug=SLUG,
            prediction_id=later,
            candidate=Candidate("gbm", 0.05),
            up_bid=0.10,
            down_bid=0.88,
            fee_rate=0.07,
        )
        is None
    )


# --- hold_pnl -----------------------------------------------------------------


def test_hold_pnl_is_recorded_for_exited_and_held_trades(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry = add_checkpoint(store, 150)
    executor = Executor("paper", store, 0.018)
    for model in ("gbm", "trend_gbm"):
        assert (
            executor.execute(
                slug=SLUG,
                prediction_id=entry,
                candidate=Candidate(model, 0.90),
                up_ask=0.70,
                down_ask=0.32,
                edge=0.03,
                fee_rate=0.07,
                stake_usd=5,
            )
            is not None
        )
    later = add_checkpoint(store, 180)
    closed = executor.evaluate_exit(
        slug=SLUG,
        prediction_id=later,
        candidate=Candidate("gbm", 0.20),
        up_bid=0.40,
        down_bid=0.58,
        fee_rate=0.07,
    )
    assert closed is not None

    store.resolve_window(SLUG, 1, None)
    rows = {str(row["model"]): row for row in store.resolved_trades()}
    size = float(rows["gbm"]["size"])
    fee = float(rows["gbm"]["fee"])
    assert rows["gbm"]["pnl"] == pytest.approx(closed.pnl)
    assert rows["gbm"]["hold_pnl"] == pytest.approx(size - 0.70 * size - fee)
    assert rows["trend_gbm"]["hold_pnl"] == pytest.approx(rows["trend_gbm"]["pnl"])

    summary = "\n".join(render_trade_summary(store.resolved_trades()))
    assert "hold" in summary and "gbm" in summary and "trend_gbm" in summary


# --- DeepSeek direct and settings ---------------------------------------------


def test_direct_prompt_no_longer_pushes_cheap_side() -> None:
    assert "cheap enough" not in SYSTEM_PROMPT
    assert "consistent with your p_up" in SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_direct_predictor_requests_reasoning_when_enabled() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"action":"skip","p_up":0.7}'},
                    }
                ]
            },
        )

    bar = Kline10s(0.0, 10.0, 100.0, 100.0, 100.0, 100.0, 1.0, 0.5)
    context = DirectMarketContext(101.0, 101.0, 100.0, 150, 0.69, 0.71, 0.29, 0.31, 0.07, 1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        predictor = DeepSeekDirectPredictor(
            client,
            api_key="secret",
            model="deepseek/deepseek-v4.1-flash",
            url="https://openrouter.test/api/v1/chat/completions",
            timeout_s=6,
            reasoning=True,
        )
        result = await predictor.predict((bar,), context)

    assert result.action == "skip"
    assert captured["reasoning"] == {"effort": "low", "exclude": True}
    assert isinstance(captured["max_tokens"], int) and captured["max_tokens"] >= 1000


def test_defaults_match_refined_strategy() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.entry_checkpoint_override == (150, 180)
    assert settings.jev_trade is False
    assert settings.market_shrink_k == pytest.approx(0.5)
    assert settings.max_model_market_gap == pytest.approx(0.15)
    assert settings.paper_slippage_ticks == 1
    assert settings.naive_spot_trade is True


def test_checkpoint_budget_uses_direct_timeout() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        jev_enabled=False,
        deepseek_direct_enabled=True,
        deepseek_direct_timeout_s=6.0,
        http_timeout_s=5.0,
    )
    assert settings.effective_checkpoint_budget_s == pytest.approx(12.0)


def test_naive_band_must_be_ordered() -> None:
    with pytest.raises(ValueError):
        Settings(  # type: ignore[call-arg]
            _env_file=None, naive_spot_min_ask=0.9, naive_spot_max_ask=0.6
        )
