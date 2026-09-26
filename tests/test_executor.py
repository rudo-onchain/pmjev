from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from pmjev.executor import Candidate, Executor, fee_per_share, simulated_pnl
from pmjev.market.live import LiveOrderResult
from pmjev.risk import LiveRiskGuard, RiskLimits
from pmjev.store import PredictionRecord, Store, TradeRecord


def test_fee_model_peaks_at_half() -> None:
    assert fee_per_share(0.5, 0.07) == pytest.approx(0.0175)
    assert fee_per_share(0.0, 0.07) == 0.0
    assert fee_per_share(1.0, 0.07) == 0.0
    assert fee_per_share(0.25, 0.07) == pytest.approx(fee_per_share(0.75, 0.07))


@pytest.mark.parametrize(
    ("side", "outcome", "expected"),
    [("up", 1, 0.39), ("up", 0, -0.61), ("down", 0, 0.39), ("down", 1, -0.61)],
)
def test_pnl_simulation(side: str, outcome: int, expected: float) -> None:
    assert simulated_pnl(  # type: ignore[arg-type]
        side=side, price=0.60, size=1.0, fee=0.01, outcome=outcome
    ) == pytest.approx(expected)


def make_store(tmp_path: Path) -> Store:
    store = Store(f"sqlite:///{tmp_path / 'executor.sqlite'}")
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
    return store


def test_paper_trade_spends_configured_stake(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = store.add_prediction(
        PredictionRecord(
            slug="btc-updown-5m-1",
            t_elapsed=60,
            ts=1.0,
            spot_chainlink=101.0,
            spot_binance=101.0,
            sigma_1s=0.001,
            up_bid=0.40,
            up_ask=0.44,
            down_ask=0.58,
            depth_ask_usd=20.0,
            p_jev=None,
            p_jev_mkt=None,
            p_gbm=0.9,
            jev_latency_ms=None,
            jev_error=None,
            state_json="{}",
        )
    )
    trade = Executor("paper", store, 0.018).execute(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("gbm", 0.9),
        up_ask=0.44,
        down_ask=0.58,
        edge=0.03,
        stake_usd=20,
    )
    assert trade is not None
    assert trade.side == "up"
    assert trade.price * trade.size == pytest.approx(20)
    assert trade.fee == pytest.approx(fee_per_share(0.44, 0.018 * 4) * trade.size)


def test_paper_entry_uses_available_side_when_other_ask_is_missing(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = _prediction(store, "btc-updown-5m-1", time.time())

    trade = Executor("paper", store, 0.018).execute(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("gbm", 0.10),
        up_ask=None,
        down_ask=0.40,
        edge=0.03,
        stake_usd=20,
    )

    assert trade is not None
    assert trade.side == "down"
    assert trade.price == pytest.approx(0.40)


def test_direct_candidate_buys_requested_side_when_it_clears_edge(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = _prediction(store, "btc-updown-5m-1", time.time())

    trade = Executor("paper", store, 0.018).execute(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("deepseek_direct", 0.65, requested_side="down"),
        up_ask=0.30,
        down_ask=0.10,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
    )

    assert trade is not None
    assert trade.side == "down"
    assert trade.price == pytest.approx(0.10)


def test_direct_candidate_is_skipped_when_requested_side_has_no_edge(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    prediction_id = _prediction(store, "btc-updown-5m-1", time.time())

    trade = Executor("paper", store, 0.018).execute(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("deepseek_direct", 0.65, requested_side="down"),
        up_ask=0.30,
        down_ask=0.40,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
    )

    assert trade is None


def test_entry_is_blocked_when_reference_and_feature_feeds_straddle_target(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    prediction_id = _prediction(store, "btc-updown-5m-1", time.time())

    trade = Executor("paper", store, 0.018).execute(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("jev", 0.35),
        up_ask=0.73,
        down_ask=0.28,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        spot=83_631.67,
        feature_spot=83_747.40,
        price_to_beat=83_698.13,
    )

    assert trade is None


def test_entry_is_blocked_when_model_and_market_disagree_beyond_limit(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    prediction_id = _prediction(store, "btc-updown-5m-1", time.time())

    trade = Executor("paper", store, 0.018).execute(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("jev", 0.35),
        up_ask=0.73,
        down_ask=0.28,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        spot=99,
        feature_spot=99,
        price_to_beat=100,
        market_probability_up=0.725,
        max_model_market_gap=0.25,
    )

    assert trade is None


def _prediction(store: Store, slug: str, ts: float) -> int:
    return store.add_prediction(
        PredictionRecord(
            slug=slug,
            t_elapsed=60,
            ts=ts,
            spot_chainlink=101.0,
            spot_binance=101.0,
            sigma_1s=0.001,
            up_bid=0.40,
            up_ask=0.44,
            down_ask=0.58,
            depth_ask_usd=20.0,
            p_jev=None,
            p_jev_mkt=None,
            p_gbm=0.9,
            jev_latency_ms=None,
            jev_error=None,
            state_json="{}",
        )
    )


def _checkpoint(
    store: Store,
    *,
    slug: str = "btc-updown-5m-1",
    elapsed: int,
    probability_up: float,
) -> int:
    return store.add_prediction(
        PredictionRecord(
            slug=slug,
            t_elapsed=elapsed,
            ts=float(elapsed),
            spot_chainlink=101.0,
            spot_binance=101.0,
            sigma_1s=0.001,
            up_bid=0.30,
            up_ask=0.32,
            down_ask=0.72,
            depth_ask_usd=20.0,
            p_jev=probability_up,
            p_jev_mkt=probability_up,
            p_gbm=probability_up,
            jev_latency_ms=None,
            jev_error=None,
            state_json="{}",
        )
    )


def test_trend_gbm_position_opened_at_240_can_exit_at_280(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry_prediction = _checkpoint(store, elapsed=240, probability_up=0.90)
    executor = Executor("paper", store, 0.018)
    trade = executor.execute(
        slug="btc-updown-5m-1",
        prediction_id=entry_prediction,
        candidate=Candidate("trend_gbm", 0.90),
        up_ask=0.68,
        down_ask=0.34,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=6.80,
        spot=101.0,
        price_to_beat=100.0,
    )
    assert trade is not None and trade.model == "trend_gbm"

    exit_prediction = _checkpoint(store, elapsed=280, probability_up=0.25)
    closed = executor.evaluate_exit(
        slug="btc-updown-5m-1",
        prediction_id=exit_prediction,
        candidate=Candidate("trend_gbm", 0.25),
        up_bid=0.30,
        down_bid=0.68,
        fee_rate=0.07,
        spot=101.0,
        price_to_beat=100.0,
    )

    assert closed is not None
    assert closed.model == "trend_gbm"
    assert closed.exit_price == pytest.approx(0.30)
    assert (
        executor.execute(
            slug="btc-updown-5m-1",
            prediction_id=exit_prediction,
            candidate=Candidate("trend_gbm", 0.90),
            up_ask=0.30,
            down_ask=0.72,
            edge=0.03,
            fee_rate=0.07,
            stake_usd=6.80,
            spot=101.0,
            price_to_beat=100.0,
        )
        is None
    )


def test_up_position_exits_at_bid_and_resolution_does_not_overwrite_pnl(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    entry_prediction = _checkpoint(store, elapsed=60, probability_up=0.90)
    executor = Executor("paper", store, 0.018)
    trade = executor.execute(
        slug="btc-updown-5m-1",
        prediction_id=entry_prediction,
        candidate=Candidate("jev", 0.90),
        up_ask=0.68,
        down_ask=0.34,
        edge=0.03,
        fee_rate=0.07,
        fee_exponent=1,
        stake_usd=6.80,
    )
    assert trade is not None

    exit_prediction = _checkpoint(store, elapsed=150, probability_up=0.25)
    closed = executor.evaluate_exit(
        slug="btc-updown-5m-1",
        prediction_id=exit_prediction,
        candidate=Candidate("jev", 0.25),
        up_bid=0.30,
        down_bid=0.68,
        fee_rate=0.07,
        fee_exponent=1,
    )

    assert closed is not None
    expected = (
        0.30 * trade.size
        - 0.68 * trade.size
        - trade.fee
        - fee_per_share(0.30, 0.07) * trade.size
    )
    assert closed.exit_price == pytest.approx(0.30)
    assert closed.pnl == pytest.approx(expected)
    assert (
        executor.execute(
            slug="btc-updown-5m-1",
            prediction_id=exit_prediction,
            candidate=Candidate("jev", 0.90),
            up_ask=0.30,
            down_ask=0.72,
            edge=0.03,
            fee_rate=0.07,
            stake_usd=6.80,
        )
        is None
    )

    store.mark_resolved("btc-updown-5m-1", 0, None)
    store.settle_trades("btc-updown-5m-1", 0)
    settled = store.resolved_trades()[0]
    assert settled["exit_price"] == pytest.approx(0.30)
    assert settled["pnl"] == pytest.approx(expected)


def test_up_position_holds_when_model_probability_still_clears_bid(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry_prediction = _checkpoint(store, elapsed=60, probability_up=0.90)
    executor = Executor("paper", store, 0.018)
    trade = executor.execute(
        slug="btc-updown-5m-1",
        prediction_id=entry_prediction,
        candidate=Candidate("jev", 0.90),
        up_ask=0.68,
        down_ask=0.34,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=6.80,
    )
    assert trade is not None

    later_prediction = _checkpoint(store, elapsed=150, probability_up=0.80)
    assert (
        executor.evaluate_exit(
            slug="btc-updown-5m-1",
            prediction_id=later_prediction,
            candidate=Candidate("jev", 0.80),
            up_bid=0.30,
            down_bid=0.68,
            fee_rate=0.07,
        )
        is None
    )

    store.mark_resolved("btc-updown-5m-1", 1, None)
    store.settle_trades("btc-updown-5m-1", 1)
    settled = store.resolved_trades()[0]
    assert settled["exit_price"] is None
    assert settled["pnl"] == pytest.approx(trade.size - 0.68 * trade.size - trade.fee)


def test_down_position_exits_only_against_down_bid(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry_prediction = _checkpoint(store, elapsed=60, probability_up=0.10)
    executor = Executor("paper", store, 0.018)
    trade = executor.execute(
        slug="btc-updown-5m-1",
        prediction_id=entry_prediction,
        candidate=Candidate("jev", 0.10),
        up_ask=0.70,
        down_ask=0.68,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=6.80,
    )
    assert trade is not None and trade.side == "down"

    exit_prediction = _checkpoint(store, elapsed=150, probability_up=0.75)
    closed = executor.evaluate_exit(
        slug="btc-updown-5m-1",
        prediction_id=exit_prediction,
        candidate=Candidate("jev", 0.75),
        up_bid=0.05,
        down_bid=0.30,
        fee_rate=0.07,
    )

    assert closed is not None
    assert closed.exit_price == pytest.approx(0.30)
    assert closed.pnl == pytest.approx(
        0.30 * trade.size
        - 0.68 * trade.size
        - trade.fee
        - fee_per_share(0.30, 0.07) * trade.size
    )


def test_jev_exit_does_not_close_jev_market_position(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry_prediction = _checkpoint(store, elapsed=60, probability_up=0.90)
    executor = Executor("paper", store, 0.018)
    for model in ("jev", "jev_mkt"):
        assert (
            executor.execute(
                slug="btc-updown-5m-1",
                prediction_id=entry_prediction,
                candidate=Candidate(model, 0.90),
                up_ask=0.68,
                down_ask=0.34,
                edge=0.03,
                fee_rate=0.07,
                stake_usd=6.80,
            )
            is not None
        )

    later_prediction = _checkpoint(store, elapsed=150, probability_up=0.25)
    assert (
        executor.evaluate_exit(
            slug="btc-updown-5m-1",
            prediction_id=later_prediction,
            candidate=Candidate("jev", 0.25),
            up_bid=0.30,
            down_bid=0.68,
            fee_rate=0.07,
        )
        is not None
    )
    assert (
        executor.evaluate_exit(
            slug="btc-updown-5m-1",
            prediction_id=later_prediction,
            candidate=Candidate("jev_mkt", 0.80),
            up_bid=0.30,
            down_bid=0.68,
            fee_rate=0.07,
        )
        is None
    )

    store.mark_resolved("btc-updown-5m-1", 0, None)
    store.settle_trades("btc-updown-5m-1", 0)
    trades = {str(row["model"]): row for row in store.resolved_trades()}
    assert trades["jev"]["exit_price"] == pytest.approx(0.30)
    assert trades["jev_mkt"]["exit_price"] is None


def test_deepseek_cannot_execute_in_shadow_mode(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = _checkpoint(store, elapsed=60, probability_up=0.90)
    executor = Executor("shadow", store, 0.018)

    with pytest.raises(ValueError, match="restricted to paper mode"):
        executor.execute(
            slug="btc-updown-5m-1",
            prediction_id=prediction_id,
            candidate=Candidate("deepseek", 0.90),
            up_ask=0.68,
            down_ask=0.34,
            edge=0.03,
            fee_rate=0.07,
            stake_usd=6.80,
        )


def test_model_at_daily_loss_limit_can_still_exit_open_position(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    entry_prediction = _checkpoint(store, elapsed=60, probability_up=0.90)
    executor = Executor("paper", store, 0.018, daily_loss_limit_usd=25.0)
    assert (
        executor.execute(
            slug="btc-updown-5m-1",
            prediction_id=entry_prediction,
            candidate=Candidate("jev", 0.90),
            up_ask=0.68,
            down_ask=0.34,
            edge=0.03,
            fee_rate=0.07,
            stake_usd=6.80,
        )
        is not None
    )

    store.upsert_window(
        slug="btc-updown-5m-loss",
        asset="btc",
        window_start=2,
        up_token="up",
        down_token="down",
        price_to_beat=100.0,
        status="resolved",
    )
    loss_prediction = _prediction(store, "btc-updown-5m-loss", time.time())
    store.add_trade(
        TradeRecord(
            prediction_id=loss_prediction,
            model="jev",
            mode="paper",
            side="up",
            price=0.50,
            size=50.0,
            fee=0.0,
            pnl=-25.0,
        )
    )
    assert store.settled_pnl("jev", 0) <= -25.0

    exit_prediction = _checkpoint(store, elapsed=150, probability_up=0.25)
    closed = executor.evaluate_exit(
        slug="btc-updown-5m-1",
        prediction_id=exit_prediction,
        candidate=Candidate("jev", 0.25),
        up_bid=0.30,
        down_bid=0.68,
        fee_rate=0.07,
    )
    assert closed is not None
    assert closed.exit_price == pytest.approx(0.30)


def test_missing_exit_bid_logs_and_keeps_position_open(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = make_store(tmp_path)
    entry_prediction = _checkpoint(store, elapsed=60, probability_up=0.90)
    executor = Executor("paper", store, 0.018)
    assert (
        executor.execute(
            slug="btc-updown-5m-1",
            prediction_id=entry_prediction,
            candidate=Candidate("jev", 0.90),
            up_ask=0.68,
            down_ask=0.34,
            edge=0.03,
            fee_rate=0.07,
            stake_usd=6.80,
        )
        is not None
    )
    later_prediction = _checkpoint(store, elapsed=150, probability_up=0.25)

    with caplog.at_level(logging.INFO, logger="pmjev.executor"):
        closed = executor.evaluate_exit(
            slug="btc-updown-5m-1",
            prediction_id=later_prediction,
            candidate=Candidate("jev", 0.25),
            up_bid=None,
            down_bid=0.68,
            fee_rate=0.07,
        )

    assert closed is None
    assert "missing bid model=jev slug=btc-updown-5m-1 side=up" in caplog.text
    store.mark_resolved("btc-updown-5m-1", 0, None)
    store.settle_trades("btc-updown-5m-1", 0)
    assert store.resolved_trades()[0]["exit_price"] is None


def test_daily_loss_blocks_only_the_losing_model(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_window(
        slug="btc-updown-5m-2",
        asset="btc",
        window_start=2,
        up_token="up",
        down_token="down",
        price_to_beat=100.0,
        status="open",
    )
    now = time.time()
    losing = _prediction(store, "btc-updown-5m-1", now)
    store.add_trade(
        TradeRecord(
            prediction_id=losing,
            model="jev",
            mode="paper",
            side="down",
            price=0.40,
            size=50.0,
            fee=1.0,
            pnl=-25.0,
        )
    )
    yesterday = _prediction(store, "btc-updown-5m-2", now - 2 * 86_400)
    store.add_trade(
        TradeRecord(
            prediction_id=yesterday,
            model="gbm",
            mode="paper",
            side="up",
            price=0.40,
            size=50.0,
            fee=1.0,
            pnl=-100.0,
        )
    )
    store.upsert_window(
        slug="btc-updown-5m-3",
        asset="btc",
        window_start=3,
        up_token="up",
        down_token="down",
        price_to_beat=100.0,
        status="open",
    )
    fresh = _prediction(store, "btc-updown-5m-3", now)
    executor = Executor("paper", store, 0.018, daily_loss_limit_usd=25)
    blocked = executor.execute(
        slug="btc-updown-5m-3",
        prediction_id=fresh,
        candidate=Candidate("jev", 0.1),
        up_ask=0.80,
        down_ask=0.30,
        edge=0.03,
        stake_usd=20,
    )
    allowed = executor.execute(
        slug="btc-updown-5m-3",
        prediction_id=fresh,
        candidate=Candidate("gbm", 0.9),
        up_ask=0.44,
        down_ask=0.58,
        edge=0.03,
        stake_usd=20,
    )
    assert blocked is None
    assert allowed is not None
    assert allowed.model == "gbm"


def test_shadow_records_order_without_a_live_gateway(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = _prediction(store, "btc-updown-5m-1", time.time())
    trade = Executor("shadow", store, 0.018).execute(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("gbm", 0.8),
        up_ask=0.5,
        down_ask=0.5,
        edge=0.03,
        stake_usd=10,
    )
    assert trade is not None
    assert trade.mode == "shadow"
    assert trade.order_id is None


class FakeLiveGateway:
    def __init__(self) -> None:
        self.orders: list[tuple[str, float, float]] = []

    async def buy_fok(
        self, *, token_id: str, amount_usd: float, max_price: float
    ) -> LiveOrderResult:
        self.orders.append((token_id, amount_usd, max_price))
        return LiveOrderResult(
            order_id="order-1",
            status="matched",
            spent=amount_usd,
            size=amount_usd / max_price,
            fill_price=max_price,
        )

    async def redeem(self, *, condition_id: str) -> str:
        return f"tx-{condition_id}"

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_live_places_fok_at_observed_ask_after_risk_checks(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = _prediction(store, "btc-updown-5m-1", time.time())
    gateway = FakeLiveGateway()
    guard = LiveRiskGuard(
        store,
        RiskLimits(max_notional_usd=30, max_trade_usd=10, daily_loss_limit_usd=25),
        stop_file=tmp_path / "STOP",
    )
    executor = Executor(
        "live",
        store,
        0.018,
        live_gateway=gateway,
        live_risk=guard,
        live_min_shares=5,
    )
    now = time.time()
    trade = await executor.execute_async(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("jev", 0.9),
        up_ask=0.50,
        down_ask=0.52,
        edge=0.03,
        stake_usd=10,
        up_token="up-token",
        down_token="down-token",
        reference_timestamp=now,
    )
    assert trade is not None
    assert trade.mode == "live"
    assert trade.order_id == "order-1"
    assert gateway.orders == [("up-token", 10, 0.50)]


@pytest.mark.asyncio
async def test_live_stop_file_blocks_before_gateway(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = _prediction(store, "btc-updown-5m-1", time.time())
    stop_file = tmp_path / "STOP"
    stop_file.touch()
    gateway = FakeLiveGateway()
    guard = LiveRiskGuard(
        store,
        RiskLimits(max_notional_usd=30, max_trade_usd=10, daily_loss_limit_usd=25),
        stop_file=stop_file,
    )
    executor = Executor("live", store, 0.018, live_gateway=gateway, live_risk=guard)
    trade = await executor.execute_async(
        slug="btc-updown-5m-1",
        prediction_id=prediction_id,
        candidate=Candidate("jev", 0.9),
        up_ask=0.50,
        down_ask=0.52,
        edge=0.03,
        stake_usd=10,
        up_token="up-token",
        down_token="down-token",
        reference_timestamp=time.time(),
    )
    assert trade is None
    assert gateway.orders == []
