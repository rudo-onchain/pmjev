"""Async scheduler and application composition for every execution mode."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from functools import partial

import httpx

from pmjev.alerts import TelegramAlerts
from pmjev.assets import (
    AssetConfig,
    BinanceSource,
    HyperliquidSource,
    build_slug,
    load_assets,
)
from pmjev.config import Settings
from pmjev.executor import (
    AttemptContext,
    Candidate,
    Executor,
    Side,
    TradeAction,
    anchor_to_market,
    fee_per_share,
)
from pmjev.features import build_features
from pmjev.feeds.base import FeatureSource
from pmjev.feeds.binance import BinanceFeed
from pmjev.feeds.chainlink import ChainlinkFeed
from pmjev.feeds.hyperliquid import HyperliquidFeed
from pmjev.feeds.polybolt import PolyBoltFeed
from pmjev.market.clob import BookSnapshot, ClobClient
from pmjev.market.gamma import GammaClient, Market
from pmjev.market.live import PolymarketLiveGateway
from pmjev.predictors.deepseek import DeepSeekPredictor, DeepSeekResult
from pmjev.predictors.deepseek_direct import (
    DeepSeekDirectPredictor,
    DeepSeekDirectResult,
    DirectAction,
    DirectMarketContext,
)
from pmjev.predictors.gbm import gbm_probability, trend_gbm_probability
from pmjev.predictors.jev import JevPredictor, JevResult
from pmjev.resolver import Resolver
from pmjev.risk import LiveRiskGuard, RiskLimits
from pmjev.store import PredictionRecord, StoreBackend, create_store

logger = logging.getLogger(__name__)

AI_MODELS = frozenset({"jev", "jev_mkt", "deepseek", "deepseek_direct"})
# Weight of each new observation in the reference/feature basis EMA (~7 per window).
BASIS_EMA_ALPHA = 0.2


def naive_spot_side(
    *,
    spot: float,
    price_to_beat: float,
    up_ask: float | None,
    down_ask: float | None,
    min_ask: float,
    max_ask: float,
) -> Side | None:
    """Return the side the reference spot is on when its ask sits inside the band."""

    side: Side = "up" if spot >= price_to_beat else "down"
    ask = up_ask if side == "up" else down_ask
    if ask is None or not min_ask <= ask <= max_ask:
        return None
    return side


def checkpoint_candidates(
    *,
    p_gbm: float,
    p_jev: float | None,
    p_jev_mkt: float | None,
    gbm_trade: bool,
    p_trend_gbm: float,
    trend_gbm_trade: bool,
    jev_trade: bool = True,
    jev_action: TradeAction | None = None,
    jev_mkt_action: TradeAction | None = None,
    p_deepseek: float | None = None,
    deepseek_action: TradeAction | None = None,
    deepseek_trade: bool = False,
    p_deepseek_direct: float | None = None,
    deepseek_direct_action: DirectAction | None = None,
    deepseek_direct_trade: bool = False,
    allow_exit: bool = True,
    allow_entry: bool = True,
    market_mid: float | None = None,
    shrink_k: float = 1.0,
    naive_side: Side | None = None,
    naive_trade: bool = False,
    naive_max_price: float | None = None,
) -> tuple[list[Candidate], list[Candidate]]:
    """Return models eligible for exit evaluation and for new entries.

    Every model probability is anchored to the market midpoint with ``shrink_k``
    before it is used for edge or exits; the raw value is kept for the gap guard.
    """

    def candidate(model: str, probability: float, side: Side | None = None) -> Candidate:
        return Candidate(
            model,
            anchor_to_market(probability, market_mid, shrink_k),
            requested_side=side,
            raw_probability_up=probability,
        )

    candidates = [candidate("gbm", p_gbm), candidate("trend_gbm", p_trend_gbm)]
    if p_jev is not None:
        candidates.append(candidate("jev", p_jev))
    if p_jev_mkt is not None:
        candidates.append(candidate("jev_mkt", p_jev_mkt))
    if p_deepseek is not None:
        candidates.append(candidate("deepseek", p_deepseek))
    if p_deepseek_direct is not None:
        candidates.append(candidate("deepseek_direct", p_deepseek_direct))
    exit_candidates = candidates if allow_exit else []
    entry_enabled = {
        "gbm": gbm_trade,
        "trend_gbm": trend_gbm_trade,
        "jev": False,
        "jev_mkt": False,
        "deepseek": False,
        "deepseek_direct": False,
    }
    entry_candidates = (
        [item for item in candidates if entry_enabled.get(item.model, True)]
        if allow_entry
        else []
    )
    ai_entries = (
        (
            ("jev", p_jev, jev_action, jev_trade),
            ("jev_mkt", p_jev_mkt, jev_mkt_action, jev_trade),
            ("deepseek", p_deepseek, deepseek_action, deepseek_trade),
        )
        if allow_entry
        else ()
    )
    for model, probability, action, enabled in ai_entries:
        if not enabled or probability is None or action not in {"buy_up", "buy_down"}:
            continue
        ai_side: Side = "up" if action == "buy_up" else "down"
        entry_candidates.append(candidate(model, probability, ai_side))
    if (
        allow_entry
        and deepseek_direct_trade
        and p_deepseek_direct is not None
        and deepseek_direct_action in {"buy_up", "buy_down"}
    ):
        direct_side: Side = "up" if deepseek_direct_action == "buy_up" else "down"
        entry_candidates.append(candidate("deepseek_direct", p_deepseek_direct, direct_side))
    if allow_entry and naive_trade and naive_side is not None:
        entry_candidates.append(
            Candidate(
                "naive_spot",
                market_mid if market_mid is not None else 0.5,
                requested_side=naive_side,
                rule_based=True,
                max_price=naive_max_price,
            )
        )
    return exit_candidates, entry_candidates


class PaperRunner:
    def __init__(self, settings: Settings, *, no_jev: bool = False) -> None:
        self.settings = settings
        self.assets = load_assets(
            settings.assets_file,
            enabled_names=settings.enabled_asset_names,
            checkpoint_override=settings.checkpoint_override,
            edge_override=settings.edge,
            stake_override=settings.stake_usd,
        )
        self.entry_checkpoints = settings.entry_checkpoint_override
        self.exit_checkpoints = settings.exit_checkpoint_override
        self._validate_action_checkpoints()
        jev_is_enabled = settings.jev_enabled and not no_jev
        deepseek_is_enabled = settings.deepseek_enabled and not no_jev
        deepseek_direct_is_enabled = settings.deepseek_direct_enabled and not no_jev
        if jev_is_enabled and not (settings.typesafe_api_key or "").strip():
            raise ValueError("TYPESAFE_API_KEY is required for Phase 1; use --no-jev for Phase 0")
        if (deepseek_is_enabled or deepseek_direct_is_enabled) and not (
            settings.openrouter_api_key or ""
        ).strip():
            raise ValueError(
                "OPENROUTER_API_KEY is required when DEEPSEEK_ENABLED=true"
            )
        self.store: StoreBackend = create_store(
            settings.db_url,
            pool_min_size=settings.db_pool_min_size,
            pool_max_size=settings.db_pool_max_size,
            connect_timeout_s=settings.db_connect_timeout_s,
        )
        self.store.initialize()
        self.store.refresh_dashboard(
            mode=settings.mode,
            starting_balance=settings.dashboard_starting_balance_usd,
        )
        self.http = httpx.AsyncClient(timeout=settings.http_timeout_s)
        self.gamma = GammaClient(self.http, settings.gamma_url)
        self.clob = ClobClient(self.http, settings.clob_url)
        symbols = [asset.chainlink_symbol for asset in self.assets]
        self.chainlink: ChainlinkFeed | PolyBoltFeed
        if settings.use_polybolt:
            if not (
                settings.poly_api_key
                and settings.poly_api_secret
                and settings.poly_api_passphrase
            ):
                raise ValueError("PolyBolt selected without complete POLY_API_* credentials")
            self.chainlink = PolyBoltFeed(
                settings.polybolt_ws_url,
                symbols,
                api_key=settings.poly_api_key,
                secret=settings.poly_api_secret,
                passphrase=settings.poly_api_passphrase,
            )
            logger.info("reference feed=polybolt assets=%s", len(symbols))
        else:
            self.chainlink = ChainlinkFeed(
                settings.chainlink_ws_url,
                symbols,
                settings.chainlink_topic,
            )
            logger.warning(
                "reference feed=legacy RTDS; configure POLY_API_* to enable PolyBolt"
            )
        self.sources = {asset.name: self._feature_source(asset) for asset in self.assets}
        self._basis: dict[str, float] = {}
        live_gateway = None
        live_risk = None
        if settings.mode == "live":
            assert settings.poly_private_key is not None
            assert settings.poly_wallet is not None
            assert settings.poly_api_key is not None
            assert settings.poly_api_secret is not None
            assert settings.poly_api_passphrase is not None
            assert settings.max_notional_usd is not None
            live_gateway = PolymarketLiveGateway(
                private_key=settings.poly_private_key,
                wallet=settings.poly_wallet,
                api_key=settings.poly_api_key,
                api_secret=settings.poly_api_secret,
                api_passphrase=settings.poly_api_passphrase,
            )
            live_risk = LiveRiskGuard(
                self.store,
                RiskLimits(
                    max_notional_usd=settings.max_notional_usd,
                    max_trade_usd=settings.live_max_trade_usd,
                    daily_loss_limit_usd=settings.daily_loss_limit_usd,
                    consecutive_loss_limit=settings.consecutive_loss_limit,
                    loss_pause_seconds=settings.loss_pause_seconds,
                    max_drawdown_usd=settings.max_drawdown_usd,
                    reference_stale_seconds=settings.reference_stale_seconds,
                    jev_error_window_seconds=settings.jev_error_window_seconds,
                    jev_error_rate_limit=settings.jev_error_rate_limit,
                ),
                stop_file=settings.stop_file,
                reset_at=settings.risk_reset_at,
            )
        self.executor = Executor(
            settings.mode,
            self.store,
            settings.fee_peak,
            daily_loss_limit_usd=settings.daily_loss_limit_usd,
            live_gateway=live_gateway,
            live_risk=live_risk,
            live_min_shares=settings.live_min_shares,
            paper_early_exits=settings.paper_early_exits,
            paper_slippage_ticks=settings.paper_slippage_ticks,
        )
        if not settings.gbm_trade:
            logger.info("gbm predictions are recorded but gbm does not trade")
        if not settings.trend_gbm_trade:
            logger.info("trend_gbm predictions are recorded but trend_gbm does not trade")
        if deepseek_is_enabled and not settings.deepseek_trade:
            logger.info("deepseek predictions are recorded but deepseek does not trade")
        if deepseek_direct_is_enabled and not settings.deepseek_direct_trade:
            logger.info(
                "deepseek_direct decisions are recorded but deepseek_direct does not trade"
            )
        self.jev = (
            JevPredictor(settings.jev_timeout_s, settings.typesafe_api_key)
            if jev_is_enabled
            else None
        )
        self.deepseek = (
            DeepSeekPredictor(
                self.http,
                api_key=settings.openrouter_api_key or "",
                model=settings.deepseek_model,
                url=settings.openrouter_url,
                timeout_s=settings.deepseek_timeout_s,
            )
            if deepseek_is_enabled
            else None
        )
        self.deepseek_direct = (
            DeepSeekDirectPredictor(
                self.http,
                api_key=settings.openrouter_api_key or "",
                model=settings.deepseek_model,
                url=settings.openrouter_url,
                timeout_s=settings.deepseek_direct_timeout_s,
                reasoning=settings.deepseek_direct_reasoning,
            )
            if deepseek_direct_is_enabled
            else None
        )
        logger.info(
            "checkpoint budget_s=%.1f http_timeout_s=%.1f jev_timeout_s=%.1f "
            "deepseek_timeout_s=%.1f",
            settings.effective_checkpoint_budget_s,
            settings.http_timeout_s,
            settings.jev_timeout_s,
            settings.deepseek_timeout_s,
        )
        self.resolver = Resolver(self.store, self.gamma, redeemer=live_gateway)
        self.alerts = TelegramAlerts(
            store=self.store,
            client=self.http,
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            message_thread_id=settings.telegram_message_thread_id,
        )
        if self.alerts.enabled:
            logger.info("telegram alerts enabled")

    def _validate_action_checkpoints(self) -> None:
        for asset in self.assets:
            prediction_checkpoints = set(asset.checkpoints)
            for setting, checkpoints in (
                ("ENTRY_CHECKPOINTS", self.entry_checkpoints),
                ("EXIT_CHECKPOINTS", self.exit_checkpoints),
            ):
                if checkpoints is None:
                    continue
                missing = set(checkpoints) - prediction_checkpoints
                if missing:
                    values = ", ".join(str(value) for value in sorted(missing))
                    raise ValueError(
                        f"{setting} contains checkpoints not collected for {asset.name}: {values}"
                    )

    def _feature_source(self, asset: AssetConfig) -> FeatureSource:
        source = asset.feature_source
        if isinstance(source, BinanceSource):
            return BinanceFeed(
                self.http,
                self.settings.binance_url,
                self.settings.binance_ws_url,
                source.symbol,
            )
        if isinstance(source, HyperliquidSource):
            return HyperliquidFeed(
                self.http,
                self.settings.hyperliquid_url,
                self.settings.hyperliquid_ws_url,
                source.coin,
            )
        raise TypeError(f"Unsupported feature source: {source}")

    async def close(self) -> None:
        await self.alerts.close()
        await self.executor.close()
        self.chainlink.close()
        for source in self.sources.values():
            source.close()
        await self.http.aclose()
        await asyncio.to_thread(self.store.close)

    async def _open_asset(
        self, asset: AssetConfig, window_start: int
    ) -> tuple[AssetConfig, Market] | None:
        slug = build_slug(asset, window_start)
        try:
            market = await self.gamma.market(slug)
            if self.settings.use_polybolt:
                if market.twap_lookback_seconds != 60:
                    raise ValueError(
                        f"{slug} requires {market.twap_lookback_seconds}s TWAP; "
                        "PolyBolt adapter provides 60s"
                    )
            else:
                expected_topic = {
                    30: "crypto_prices_twap_thirty",
                    60: "crypto_prices_twap_sixty",
                }[market.twap_lookback_seconds]
                if self.settings.chainlink_topic != expected_topic:
                    raise ValueError(
                        f"{slug} requires {expected_topic}, "
                        f"configured {self.settings.chainlink_topic}"
                    )
            deadline = time.monotonic() + 2.0
            tick = self.chainlink.price_to_beat(asset.chainlink_symbol, window_start)
            while tick is None and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                tick = self.chainlink.price_to_beat(asset.chainlink_symbol, window_start)
            if tick is None:
                await asyncio.to_thread(
                    self.store.upsert_window,
                    slug=slug,
                    asset=asset.name,
                    window_start=window_start,
                    up_token=market.up_token,
                    down_token=market.down_token,
                    condition_id=market.condition_id,
                    price_to_beat=None,
                    status="no_open",
                    window_seconds=asset.window_seconds,
                    fee_rate=market.fee_rate,
                    fee_exponent=market.fee_exponent,
                )
                logger.error("%s status=no_open", slug)
                return None
            await asyncio.to_thread(
                self.store.upsert_window,
                slug=slug,
                asset=asset.name,
                window_start=window_start,
                up_token=market.up_token,
                down_token=market.down_token,
                condition_id=market.condition_id,
                price_to_beat=tick.price,
                status="open",
                window_seconds=asset.window_seconds,
                fee_rate=market.fee_rate,
                fee_exponent=market.fee_exponent,
            )
            return asset, market
        except Exception:
            await asyncio.to_thread(
                self.store.upsert_window,
                slug=slug,
                asset=asset.name,
                window_start=window_start,
                up_token=None,
                down_token=None,
                price_to_beat=None,
                status="error",
                window_seconds=asset.window_seconds,
            )
            logger.exception("failed to open asset window %s", slug)
            return None

    @staticmethod
    def _jev_error(blind: JevResult, market: JevResult | None) -> str | None:
        failures = []
        if blind.error:
            failures.append(f"blind: {blind.error}")
        if market is not None and market.error:
            failures.append(f"market: {market.error}")
        return "; ".join(failures) or None

    def _basis_adjusted_feature_spot(
        self, asset: str, reference_spot: float, feature_spot: float
    ) -> float:
        """Shift the feature-source spot by the running reference/feature basis.

        Binance BTCUSDT trades a few bps away from Chainlink BTC/USD. Without this
        shift the feed-straddle guard blocks one side far more than the other. The
        basis used is the EMA *before* this observation, so a sudden divergence at
        this checkpoint still trips the guard.
        """

        previous = self._basis.get(asset)
        difference = reference_spot - feature_spot
        self._basis[asset] = (
            difference
            if previous is None
            else previous + BASIS_EMA_ALPHA * (difference - previous)
        )
        return feature_spot + previous if previous is not None else feature_spot

    async def _trade_phase(
        self,
        *,
        asset: AssetConfig,
        market: Market,
        prediction_id: int,
        exit_candidates: list[Candidate],
        entry_candidates: list[Candidate],
        snapshot: BookSnapshot,
        price_to_beat: float,
        reference_spot: float,
        reference_timestamp: float,
        feature_spot: float,
        market_mid: float | None,
    ) -> None:
        """Re-read the book, then run exits and entries against that fresh book."""

        if not exit_candidates and not entry_candidates:
            return
        try:
            fresh = await self.clob.snapshot(market.up_token, market.down_token)
        except Exception:
            logger.warning(
                "fresh book read failed; skipping trades slug=%s models=%s",
                market.slug,
                ",".join(c.model for c in [*exit_candidates, *entry_candidates]),
                exc_info=True,
            )
            return
        for candidate in exit_candidates:
            closed_trade = await asyncio.to_thread(
                self.executor.evaluate_exit,
                slug=market.slug,
                prediction_id=prediction_id,
                candidate=candidate,
                up_bid=fresh.up_bid,
                down_bid=fresh.down_bid,
                fee_rate=market.fee_rate,
                fee_exponent=market.fee_exponent,
                spot=reference_spot,
                price_to_beat=price_to_beat,
            )
            if closed_trade is not None:
                self.alerts.trade_exited(asset=asset.name, trade=closed_trade)
        for candidate in entry_candidates:
            opened_trade = await self.executor.execute_async(
                slug=market.slug,
                prediction_id=prediction_id,
                candidate=candidate,
                up_ask=fresh.up_ask,
                down_ask=fresh.down_ask,
                edge=asset.edge,
                fee_rate=market.fee_rate,
                fee_exponent=market.fee_exponent,
                stake_usd=asset.stake_usd,
                up_token=market.up_token,
                down_token=market.down_token,
                reference_timestamp=reference_timestamp,
                spot=reference_spot,
                feature_spot=feature_spot,
                price_to_beat=price_to_beat,
                market_probability_up=market_mid,
                max_model_market_gap=self.settings.max_model_market_gap,
                up_levels=fresh.up_asks,
                down_levels=fresh.down_asks,
                attempt=AttemptContext(
                    snapshot_up_ask=snapshot.up_ask,
                    snapshot_down_ask=snapshot.down_ask,
                    snapshot_ts=snapshot.fetched_at,
                    decided_at=fresh.fetched_at or time.time(),
                ),
            )
            if opened_trade is not None:
                self.alerts.trade_opened(
                    asset=asset.name,
                    model=candidate.model,
                    probability_up=candidate.probability_up,
                    trade=opened_trade,
                )

    async def _checkpoint(
        self,
        asset: AssetConfig,
        market: Market,
        window_start: int,
        elapsed: int,
    ) -> bool:
        slug = market.slug
        try:
            chainlink_tick = self.chainlink.latest(asset.chainlink_symbol)
            if (
                chainlink_tick is None
                or chainlink_tick.timestamp
                < time.time() - self.settings.reference_stale_seconds
            ):
                raise RuntimeError("reference feed has no fresh tick")
            window_row = await asyncio.to_thread(self.store.window_by_slug, slug)
            if window_row is None or window_row["price_to_beat"] is None:
                raise RuntimeError("window has no price_to_beat")
            price_to_beat = float(window_row["price_to_beat"])
            now = time.time()
            seconds_remaining = asset.window_seconds - elapsed
            book, features = await asyncio.gather(
                self.clob.snapshot(market.up_token, market.down_token),
                build_features(
                    self.sources[asset.name],
                    price_to_beat=price_to_beat,
                    chainlink_spot=chainlink_tick.price,
                    now=now,
                    seconds_remaining=seconds_remaining,
                ),
            )
            blind_state = features.state
            market_mid = (
                (book.up_bid + book.up_ask) / 2
                if book.up_bid is not None and book.up_ask is not None
                else None
            )
            if book.up_ask is None or book.down_ask is None:
                logger.info(
                    "checkpoint has missing ask slug=%s elapsed=%s up_ask=%s down_ask=%s",
                    slug,
                    elapsed,
                    book.up_ask,
                    book.down_ask,
                )
            market_observations = {
                "polymarket_up_bid": book.up_bid,
                "polymarket_up_ask": book.up_ask,
                "polymarket_up_mid": market_mid,
                "polymarket_down_bid": book.down_bid,
                "polymarket_down_ask": book.down_ask,
                "fee_rate": market.fee_rate,
                "fee_exponent": market.fee_exponent,
                "up_fee_per_share": (
                    fee_per_share(book.up_ask, market.fee_rate, market.fee_exponent)
                    if book.up_ask is not None
                    else None
                ),
                "down_fee_per_share": (
                    fee_per_share(book.down_ask, market.fee_rate, market.fee_exponent)
                    if book.down_ask is not None
                    else None
                ),
            }
            market_state = {
                **blind_state,
                **{
                    key: value
                    for key, value in market_observations.items()
                    if value is not None
                },
            }
            adjusted_feature_spot = self._basis_adjusted_feature_spot(
                asset.name, chainlink_tick.price, features.feature_spot
            )

            # Start the slow AI requests first; they run while fast models trade.
            jev_task = None
            if self.jev is not None and asset.jev.enabled:
                jev_task = asyncio.create_task(
                    self.jev.predict_variants(
                        blind_state,
                        market_state
                        if asset.jev.market_variant and self.settings.jev_market_variant
                        else None,
                        slug=slug,
                        checkpoint=elapsed,
                    )
                )
            deepseek_task = (
                asyncio.create_task(
                    self.deepseek.predict(market_state, slug=slug, checkpoint=elapsed)
                )
                if self.deepseek is not None
                else None
            )
            deepseek_direct_task = (
                asyncio.create_task(
                    self.deepseek_direct.predict(
                        features.klines_10s,
                        DirectMarketContext(
                            chainlink_spot=chainlink_tick.price,
                            feature_spot=features.feature_spot,
                            price_to_beat=price_to_beat,
                            seconds_remaining=seconds_remaining,
                            up_bid=book.up_bid,
                            up_ask=book.up_ask,
                            down_bid=book.down_bid,
                            down_ask=book.down_ask,
                            fee_rate=market.fee_rate,
                            fee_exponent=market.fee_exponent,
                        ),
                        slug=slug,
                        checkpoint=elapsed,
                    )
                )
                if self.deepseek_direct is not None
                else None
            )

            p_gbm = gbm_probability(
                chainlink_tick.price, price_to_beat, features.sigma_1s, seconds_remaining
            )
            p_trend_gbm = trend_gbm_probability(
                chainlink_tick.price,
                price_to_beat,
                features.sigma_1s,
                seconds_remaining,
                return_10s_pct=float(blind_state["return_10s_pct"]),
                return_30s_pct=float(blind_state["return_30s_pct"]),
                return_60s_pct=float(blind_state["return_60s_pct"]),
                return_5m_pct=float(blind_state["return_5m_pct"]),
                order_flow_buy_ratio_60s=float(blind_state["order_flow_buy_ratio_60s"]),
            )
            allow_exit = self.exit_checkpoints is None or elapsed in self.exit_checkpoints
            allow_entry = self.entry_checkpoints is None or elapsed in self.entry_checkpoints
            state_json = json.dumps(
                {"blind": blind_state, "market": market_state}, sort_keys=True
            )

            def prediction_record(
                blind: JevResult,
                jev_market: JevResult | None,
                deepseek: DeepSeekResult,
                deepseek_direct: DeepSeekDirectResult,
            ) -> PredictionRecord:
                latencies = [blind.latency_ms]
                if jev_market is not None:
                    latencies.append(jev_market.latency_ms)
                return PredictionRecord(
                    slug=slug,
                    t_elapsed=elapsed,
                    ts=now,
                    spot_chainlink=chainlink_tick.price,
                    spot_binance=features.feature_spot,
                    sigma_1s=features.sigma_1s,
                    up_bid=book.up_bid,
                    up_ask=book.up_ask,
                    down_ask=book.down_ask,
                    depth_ask_usd=book.depth_ask_usd,
                    p_jev=blind.probability,
                    p_jev_mkt=jev_market.probability if jev_market else None,
                    jev_action=blind.action,
                    jev_mkt_action=jev_market.action if jev_market else None,
                    p_gbm=p_gbm,
                    jev_latency_ms=max(latencies) if self.jev is not None else None,
                    jev_error=self._jev_error(blind, jev_market),
                    state_json=state_json,
                    down_bid=book.down_bid,
                    p_trend_gbm=p_trend_gbm,
                    p_deepseek=deepseek.probability,
                    deepseek_action=deepseek.action,
                    deepseek_latency_ms=(
                        deepseek.latency_ms if self.deepseek is not None else None
                    ),
                    deepseek_error=deepseek.error,
                    deepseek_provider=deepseek.provider,
                    p_deepseek_direct=deepseek_direct.probability_up,
                    deepseek_direct_action=deepseek_direct.action,
                    deepseek_direct_latency_ms=(
                        deepseek_direct.latency_ms
                        if self.deepseek_direct is not None
                        else None
                    ),
                    deepseek_direct_error=deepseek_direct.error,
                    deepseek_direct_provider=deepseek_direct.provider,
                )

            empty_jev = JevResult(None, None, 0.0, None)
            empty_deepseek = DeepSeekResult(None, None, 0.0, None, None)
            empty_direct = DeepSeekDirectResult(None, None, 0.0, None, None)
            # Phase 1: store the fast predictions, then let fast models trade now.
            prediction_id = await asyncio.to_thread(
                self.store.add_prediction,
                prediction_record(empty_jev, None, empty_deepseek, empty_direct),
            )
            fast_exits, fast_entries = checkpoint_candidates(
                p_gbm=p_gbm,
                p_jev=None,
                p_jev_mkt=None,
                gbm_trade=self.settings.gbm_trade,
                p_trend_gbm=p_trend_gbm,
                trend_gbm_trade=self.settings.trend_gbm_trade,
                allow_exit=allow_exit,
                allow_entry=allow_entry,
                market_mid=market_mid,
                shrink_k=self.settings.market_shrink_k,
                naive_side=naive_spot_side(
                    spot=chainlink_tick.price,
                    price_to_beat=price_to_beat,
                    up_ask=book.up_ask,
                    down_ask=book.down_ask,
                    min_ask=self.settings.naive_spot_min_ask,
                    max_ask=self.settings.naive_spot_max_ask,
                ),
                naive_trade=self.settings.naive_spot_trade,
                naive_max_price=self.settings.naive_spot_max_ask,
            )
            trade_phase = partial(
                self._trade_phase,
                asset=asset,
                market=market,
                prediction_id=prediction_id,
                snapshot=book,
                price_to_beat=price_to_beat,
                reference_spot=chainlink_tick.price,
                reference_timestamp=chainlink_tick.timestamp,
                feature_spot=adjusted_feature_spot,
                market_mid=market_mid,
            )
            await trade_phase(exit_candidates=fast_exits, entry_candidates=fast_entries)

            # Phase 2: wait for AI models, update the same prediction row, trade them.
            blind, jev_market = (
                await jev_task if jev_task is not None else (empty_jev, None)
            )
            deepseek = await deepseek_task if deepseek_task is not None else empty_deepseek
            deepseek_direct = (
                await deepseek_direct_task
                if deepseek_direct_task is not None
                else empty_direct
            )
            if jev_task or deepseek_task or deepseek_direct_task:
                await asyncio.to_thread(
                    self.store.add_prediction,
                    prediction_record(blind, jev_market, deepseek, deepseek_direct),
                )
                ai_exits, ai_entries = checkpoint_candidates(
                    p_gbm=p_gbm,
                    p_jev=blind.probability,
                    p_jev_mkt=jev_market.probability if jev_market else None,
                    gbm_trade=False,
                    p_trend_gbm=p_trend_gbm,
                    trend_gbm_trade=False,
                    jev_trade=self.settings.jev_trade,
                    jev_action=blind.action,
                    jev_mkt_action=jev_market.action if jev_market else None,
                    p_deepseek=deepseek.probability,
                    deepseek_action=deepseek.action,
                    deepseek_trade=self.settings.deepseek_trade,
                    p_deepseek_direct=deepseek_direct.probability_up,
                    deepseek_direct_action=deepseek_direct.action,
                    deepseek_direct_trade=self.settings.deepseek_direct_trade,
                    allow_exit=allow_exit,
                    allow_entry=allow_entry,
                    market_mid=market_mid,
                    shrink_k=self.settings.market_shrink_k,
                )
                await trade_phase(
                    exit_candidates=[c for c in ai_exits if c.model in AI_MODELS],
                    entry_candidates=[c for c in ai_entries if c.model in AI_MODELS],
                )
            logger.info(
                "slug=%s checkpoint=%s market=%s gbm=%.4f trend_gbm=%.4f "
                "jev=%s jev_action=%s jev_mkt=%s jev_mkt_action=%s "
                "deepseek=%s deepseek_action=%s deepseek_direct=%s "
                "deepseek_direct_action=%s deepseek_direct_latency_ms=%s basis=%.2f",
                slug,
                elapsed,
                f"{market_mid:.4f}" if market_mid is not None else "missing-mid",
                p_gbm,
                p_trend_gbm,
                blind.probability,
                blind.action,
                jev_market.probability if jev_market else None,
                jev_market.action if jev_market else None,
                deepseek.probability,
                deepseek.action,
                deepseek_direct.probability_up,
                deepseek_direct.action,
                (
                    f"{deepseek_direct.latency_ms:.0f}"
                    if self.deepseek_direct is not None
                    else None
                ),
                adjusted_feature_spot - features.feature_spot,
            )
            return True
        except Exception:
            logger.exception("checkpoint failed slug=%s elapsed=%s", slug, elapsed)
            return False

    async def _run_window(self, assets: list[AssetConfig], window_start: int) -> None:
        opened = await asyncio.gather(*(self._open_asset(asset, window_start) for asset in assets))
        active = [item for item in opened if item is not None]
        schedule = sorted({checkpoint for asset, _ in active for checkpoint in asset.checkpoints})
        checkpoint_budget_s = self.settings.effective_checkpoint_budget_s
        if self.jev is not None and active and schedule:
            logger.info(
                "jev waiting window=%s assets=%s next_checkpoint=%s",
                window_start,
                ",".join(asset.name for asset, _ in active),
                schedule[0],
            )
        for elapsed in schedule:
            delay = window_start + elapsed - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            results = await asyncio.gather(
                *(
                    asyncio.wait_for(
                        self._checkpoint(asset, market, window_start, elapsed),
                        timeout=checkpoint_budget_s,
                    )
                    for asset, market in active
                    if elapsed in asset.checkpoints
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, TimeoutError):
                    logger.error(
                        "checkpoint exceeded %.1f-second budget elapsed=%s",
                        checkpoint_budget_s,
                        elapsed,
                    )
            if any(result is True for result in results):
                await asyncio.to_thread(
                    self.store.refresh_dashboard,
                    mode=self.settings.mode,
                    starting_balance=self.settings.dashboard_starting_balance_usd,
                )
        resolution_delay = (
            window_start + max(asset.window_seconds for asset, _ in active) + 30 - time.time()
            if active
            else 0
        )
        if resolution_delay > 0:
            await asyncio.sleep(resolution_delay)
        resolved, _ = await self.resolver.resolve_pending_details()
        if resolved:
            await asyncio.to_thread(
                self.store.refresh_dashboard,
                mode=self.settings.mode,
                starting_balance=self.settings.dashboard_starting_balance_usd,
            )
        for resolution in resolved:
            await self.alerts.window_settled(
                slug=resolution.slug, outcome=resolution.outcome
            )

    async def run_forever(self) -> None:
        logger.warning("execution mode=%s", self.settings.mode)
        feed_task = asyncio.create_task(self.chainlink.run())
        source_tasks = [asyncio.create_task(source.run()) for source in self.sources.values()]
        alerts_task = asyncio.create_task(self.alerts.run())
        tasks: set[asyncio.Task[None]] = set()
        launched: set[tuple[int, int]] = set()
        try:
            while True:
                now = int(time.time())
                for duration in sorted({asset.window_seconds for asset in self.assets}):
                    next_start = now - (now % duration) + duration
                    key = (duration, next_start)
                    if key not in launched:
                        launched.add(key)
                        group = [asset for asset in self.assets if asset.window_seconds == duration]
                        logger.info(
                            "jev idle until window=%s in %.0fs assets=%s checkpoints=%s",
                            next_start,
                            max(next_start - time.time(), 0),
                            ",".join(asset.name for asset in group),
                            ",".join(
                                str(checkpoint)
                                for checkpoint in sorted(
                                    {value for asset in group for value in asset.checkpoints}
                                )
                            )
                            if self.jev is not None
                            else "off",
                        )

                        async def launch(
                            delay: float,
                            selected: list[AssetConfig],
                            start: int,
                        ) -> None:
                            await asyncio.sleep(max(delay, 0))
                            await self._run_window(selected, start)

                        tasks.add(
                            asyncio.create_task(launch(next_start - time.time(), group, next_start))
                        )
                finished = {task for task in tasks if task.done()}
                for task in finished:
                    with suppress(Exception):
                        task.result()
                tasks -= finished
                await asyncio.sleep(1)
        finally:
            self.chainlink.close()
            feed_task.cancel()
            for source in self.sources.values():
                source.close()
            for source_task in source_tasks:
                source_task.cancel()
            for task in tasks:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await feed_task
            await asyncio.gather(*source_tasks, return_exceptions=True)
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.alerts.close()
            await asyncio.gather(alerts_task, return_exceptions=True)


async def run_collector(settings: Settings, *, no_jev: bool) -> None:
    runner = PaperRunner(settings, no_jev=no_jev)
    try:
        await runner.run_forever()
    finally:
        await runner.close()


async def run_doctor(settings: Settings) -> None:
    """Verify every Phase 0 public dependency with no persistent writes."""

    runner = PaperRunner(settings.model_copy(update={"db_url": "sqlite:///:memory:"}), no_jev=True)
    feed_tasks = [asyncio.create_task(runner.chainlink.run())]
    feed_tasks.extend(asyncio.create_task(source.run()) for source in runner.sources.values())
    try:

        async def feeds_ready() -> None:
            while any(
                runner.chainlink.latest(asset.chainlink_symbol) is None for asset in runner.assets
            ):
                await asyncio.sleep(0.05)

        await asyncio.wait_for(feeds_ready(), timeout=15)

        async def check_asset_once(asset: AssetConfig) -> str:
            now = time.time()
            window_start = int(now) - (int(now) % asset.window_seconds)
            market = await runner.gamma.market(build_slug(asset, window_start))
            if runner.settings.use_polybolt:
                if market.twap_lookback_seconds != 60:
                    raise ValueError("PolyBolt adapter currently supports 60s TWAP only")
            else:
                expected_topic = {
                    30: "crypto_prices_twap_thirty",
                    60: "crypto_prices_twap_sixty",
                }[market.twap_lookback_seconds]
                if runner.settings.chainlink_topic != expected_topic:
                    raise ValueError(
                        f"requires {expected_topic}, "
                        f"configured {runner.settings.chainlink_topic}"
                    )
            tick = runner.chainlink.latest(asset.chainlink_symbol)
            if tick is None:
                raise RuntimeError("no Chainlink TWAP tick")
            book, features = await asyncio.gather(
                runner.clob.snapshot(market.up_token, market.down_token),
                build_features(
                    runner.sources[asset.name],
                    price_to_beat=tick.price,
                    chainlink_spot=tick.price,
                    now=now,
                    seconds_remaining=asset.window_seconds,
                ),
            )
            bid_text = f"{book.up_bid:.2f}" if book.up_bid is not None else "missing"
            ask_text = f"{book.up_ask:.2f}" if book.up_ask is not None else "missing"
            return (
                f"{asset.name}: gamma=ok twap={market.twap_lookback_seconds}s "
                f"fee_rate={market.fee_rate:g} "
                f"clob={bid_text}/{ask_text} "
                f"source_spot={features.feature_spot:.6g}"
            )

        async def check_asset(asset: AssetConfig) -> str:
            try:
                return await check_asset_once(asset)
            except (httpx.TimeoutException, httpx.NetworkError):
                logger.warning("doctor retrying transient network failure for %s", asset.name)
                await asyncio.sleep(0.5)
                return await check_asset_once(asset)

        results = await asyncio.gather(
            *(check_asset(asset) for asset in runner.assets),
            return_exceptions=True,
        )
        failed = False
        for asset, result in zip(runner.assets, results, strict=True):
            if isinstance(result, BaseException):
                failed = True
                print(f"[FAIL] {asset.name}: {type(result).__name__}: {result}")
            else:
                print(f"[OK] {result}")
        if failed:
            raise RuntimeError("Phase 0 doctor found one or more failing assets")
        print("Phase 0 doctor passed for all enabled assets.")
    finally:
        runner.chainlink.close()
        for source in runner.sources.values():
            source.close()
        for task in feed_tasks:
            task.cancel()
        await asyncio.gather(*feed_tasks, return_exceptions=True)
        await runner.close()
