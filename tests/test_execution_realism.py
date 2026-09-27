"""Fresh-book execution, depth walking, entry-attempt logging, and two-phase checkpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import pmjev.main as main_module
from pmjev.assets import AssetConfig, BinanceSource, JevConfig
from pmjev.config import Settings
from pmjev.executor import AttemptContext, Candidate, Executor, fee_per_share
from pmjev.features import FeatureSnapshot
from pmjev.feeds.chainlink import PriceTick
from pmjev.main import PaperRunner
from pmjev.market.clob import BookSnapshot
from pmjev.market.gamma import Market
from pmjev.predictors.jev import JevResult
from pmjev.store import PredictionRecord, Store

SLUG = "btc-updown-5m-1000"


def make_store(tmp_path: Path) -> Store:
    store = Store(f"sqlite:///{tmp_path / 'realism.sqlite'}")
    store.initialize()
    store.upsert_window(
        slug=SLUG,
        asset="btc",
        window_start=1000,
        up_token="up",
        down_token="down",
        price_to_beat=100.0,
        status="open",
    )
    return store


def add_prediction(store: Store, elapsed: int = 150) -> int:
    return store.add_prediction(
        PredictionRecord(
            slug=SLUG,
            t_elapsed=elapsed,
            ts=1.0,
            spot_chainlink=100.5,
            spot_binance=100.5,
            sigma_1s=0.001,
            up_bid=0.69,
            up_ask=0.70,
            down_ask=0.31,
            depth_ask_usd=20.0,
            p_jev=None,
            p_jev_mkt=None,
            p_gbm=0.8,
            jev_latency_ms=None,
            jev_error=None,
            state_json="{}",
        )
    )


# --- executor: depth walk and edge-aware limit -----------------------------------


def test_entry_walks_ladder_and_records_vwap(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = add_prediction(store)
    executor = Executor("paper", store, 0.018)
    trade = executor.execute(
        slug=SLUG,
        prediction_id=prediction_id,
        candidate=Candidate("gbm", 0.95),
        up_ask=0.70,
        down_ask=0.31,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        up_levels=((0.70, 2.0), (0.72, 100.0)),
    )
    assert trade is not None
    shares = 2.0 + (5 - 0.70 * 2.0) / 0.72
    assert trade.size == pytest.approx(shares)
    assert trade.price == pytest.approx(5 / shares)
    expected_fee = fee_per_share(0.70, 0.07) * 2.0 + fee_per_share(0.72, 0.07) * (shares - 2)
    assert trade.fee == pytest.approx(expected_fee)


def test_entry_rejected_when_book_cannot_fill_up_to_limit(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = add_prediction(store)
    trade = Executor("paper", store, 0.018).execute(
        slug=SLUG,
        prediction_id=prediction_id,
        candidate=Candidate("gbm", 0.80),
        up_ask=0.70,
        down_ask=0.31,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        # Only $1.40 is priced below the edge limit (0.75); the rest is too expensive.
        up_levels=((0.70, 2.0), (0.90, 100.0)),
        attempt=AttemptContext(0.68, 0.33, snapshot_ts=10.0, decided_at=12.5),
    )
    assert trade is None
    attempt = store.entry_attempts()[0]
    assert attempt["outcome"] == "insufficient_depth"
    assert attempt["depth_to_max_usd"] == pytest.approx(1.40)
    assert attempt["snapshot_ask"] == pytest.approx(0.68)
    assert attempt["fresh_ask"] == pytest.approx(0.70)
    assert attempt["lag_ms"] == pytest.approx(2500)


def test_rule_based_limit_is_its_cap_not_the_edge(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = add_prediction(store)
    executor = Executor("paper", store, 0.018)
    candidate = Candidate(
        "naive_spot", 0.5, requested_side="up", rule_based=True, max_price=0.90
    )
    assert (
        executor.execute(
            slug=SLUG,
            prediction_id=prediction_id,
            candidate=candidate,
            up_ask=0.91,
            down_ask=0.10,
            edge=0.03,
            fee_rate=0.07,
            stake_usd=5,
            up_levels=((0.91, 100.0),),
            attempt=AttemptContext(0.85, 0.16, snapshot_ts=1.0, decided_at=1.2),
        )
        is None
    )
    attempt = store.entry_attempts()[0]
    assert attempt["outcome"] == "no_edge"
    assert attempt["max_price"] == pytest.approx(0.90)


def test_filled_attempt_is_logged_with_fill_price(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    prediction_id = add_prediction(store)
    trade = Executor("paper", store, 0.018, paper_slippage_ticks=1).execute(
        slug=SLUG,
        prediction_id=prediction_id,
        candidate=Candidate("gbm", 0.95),
        up_ask=0.70,
        down_ask=0.31,
        edge=0.03,
        fee_rate=0.07,
        stake_usd=5,
        up_levels=((0.70, 100.0),),
        attempt=AttemptContext(0.70, 0.31, snapshot_ts=1.0, decided_at=1.3),
    )
    assert trade is not None and trade.price == pytest.approx(0.71)
    attempt = store.entry_attempts()[0]
    assert attempt["outcome"] == "filled"
    assert attempt["fill_price"] == pytest.approx(0.71)


# --- runner: basis and two-phase checkpoint --------------------------------------


def bare_runner(settings: Settings) -> PaperRunner:
    runner = object.__new__(PaperRunner)
    runner.settings = settings
    runner._basis = {}
    return runner


def test_basis_uses_previous_ema_so_new_divergence_still_trips() -> None:
    runner = bare_runner(Settings(_env_file=None))  # type: ignore[call-arg]
    assert runner._basis_adjusted_feature_spot("btc", 100.0, 100.3) == pytest.approx(100.3)
    # Previous basis is -0.3, so a feature spot of 100.35 maps to 100.05.
    assert runner._basis_adjusted_feature_spot("btc", 100.0, 100.35) == pytest.approx(100.05)


class FakeClob:
    def __init__(self, books: list[BookSnapshot]) -> None:
        self._books = books
        self.calls = 0

    async def snapshot(self, up_token: str, down_token: str) -> BookSnapshot:
        book = self._books[min(self.calls, len(self._books) - 1)]
        self.calls += 1
        return book


class FakeChainlink:
    def latest(self, symbol: str) -> PriceTick:
        import time

        return PriceTick(symbol=symbol, price=100.5, timestamp=time.time())


class SlowJev:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def predict_variants(
        self, blind: dict[str, Any], market: dict[str, Any] | None, **_: Any
    ) -> tuple[JevResult, None]:
        await self.release.wait()
        return JevResult(0.82, "buy_up", 900.0, None), None


class QuietAlerts:
    def trade_opened(self, **_: Any) -> None:
        return None

    def trade_exited(self, **_: Any) -> None:
        return None


def book(up_ask: float, levels: tuple[tuple[float, float], ...], at: float) -> BookSnapshot:
    return BookSnapshot(
        up_bid=round(up_ask - 0.01, 2),
        up_ask=up_ask,
        down_bid=round(1 - up_ask - 0.01, 2),
        down_ask=round(1.01 - up_ask, 2),
        depth_ask_usd=100.0,
        up_asks=levels,
        down_asks=((round(1.01 - up_ask, 2), 100.0),),
        fetched_at=at,
    )


@pytest.mark.asyncio
async def test_fast_models_trade_on_fresh_book_before_ai_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_features(*_: Any, **__: Any) -> FeatureSnapshot:
        state = {
            "return_10s_pct": 0.0,
            "return_30s_pct": 0.0,
            "return_60s_pct": 0.0,
            "return_5m_pct": 0.0,
            "order_flow_buy_ratio_60s": 0.5,
        }
        return FeatureSnapshot(state=state, feature_spot=100.5, sigma_1s=0.0005, klines_10s=())

    monkeypatch.setattr(main_module, "build_features", fake_features)
    store = make_store(tmp_path)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        gbm_trade=False,
        trend_gbm_trade=False,
        jev_trade=True,
        naive_spot_trade=True,
        paper_slippage_ticks=1,
    )
    runner = bare_runner(settings)
    runner.store = store
    runner.clob = FakeClob(  # type: ignore[assignment]
        [
            book(0.70, ((0.70, 100.0),), at=1.0),  # checkpoint snapshot
            book(0.72, ((0.72, 3.0), (0.74, 100.0)), at=1.4),  # fresh, fast phase
            book(0.66, ((0.66, 100.0),), at=3.0),  # fresh, AI phase
        ]
    )
    runner.chainlink = FakeChainlink()  # type: ignore[assignment]
    runner.sources = {"btc": object()}  # type: ignore[dict-item]
    jev = SlowJev()
    runner.jev = jev  # type: ignore[assignment]
    runner.deepseek = None
    runner.deepseek_direct = None
    runner.entry_checkpoints = (150, 180)
    runner.exit_checkpoints = None
    runner.executor = Executor("paper", store, 0.018, paper_slippage_ticks=1)
    runner.alerts = QuietAlerts()  # type: ignore[assignment]
    asset = AssetConfig(
        name="btc",
        slug_prefix="btc-updown-5m",
        chainlink_symbol="btc/usd",
        feature_source=BinanceSource(type="binance", symbol="BTCUSDT"),
        window_seconds=300,
        checkpoints=(60, 150, 180),
        edge=0.03,
        stake_usd=5,
        jev=JevConfig(enabled=True, market_variant=False),
    )
    market = Market(
        slug=SLUG,
        up_token="up",
        down_token="down",
        fee_rate=0.07,
        fee_exponent=1,
        twap_lookback_seconds=60,
    )

    task = asyncio.create_task(runner._checkpoint(asset, market, 1000, 150))
    for _ in range(200):
        if store.has_trade(SLUG, "naive_spot"):
            break
        await asyncio.sleep(0.01)
    # naive_spot filled against the fresh ladder while Jev is still thinking.
    assert store.has_trade(SLUG, "naive_spot")
    assert not store.has_trade(SLUG, "jev")
    assert not task.done()

    jev.release.set()
    assert await task is True

    trades = {str(row["model"]): row for row in store.trades_for_slug(SLUG)}
    shares = 3.0 + (5 - 0.73 * 3.0) / 0.75
    assert trades["naive_spot"]["price"] == pytest.approx(5 / shares)
    assert trades["jev"]["price"] == pytest.approx(0.67)
    prediction = store.resolved_predictions() or []
    assert prediction == []  # window not resolved; check the stored row directly
    rows = store._connection.execute(
        "SELECT p_jev, jev_action FROM predictions WHERE slug = ?", (SLUG,)
    ).fetchall()
    assert len(rows) == 1 and rows[0]["p_jev"] == pytest.approx(0.82)
    attempts = {str(row["model"]): row for row in store.entry_attempts()}
    assert attempts["naive_spot"]["snapshot_ask"] == pytest.approx(0.70)
    assert attempts["naive_spot"]["fresh_ask"] == pytest.approx(0.72)
    assert attempts["jev"]["fresh_ask"] == pytest.approx(0.66)
    assert attempts["jev"]["lag_ms"] == pytest.approx(2000)
