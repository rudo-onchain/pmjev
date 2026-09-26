"""Async scheduler and application composition for every execution mode."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress

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
from pmjev.executor import Candidate, Executor
from pmjev.features import build_features
from pmjev.feeds.base import FeatureSource
from pmjev.feeds.binance import BinanceFeed
from pmjev.feeds.chainlink import ChainlinkFeed
from pmjev.feeds.hyperliquid import HyperliquidFeed
from pmjev.feeds.polybolt import PolyBoltFeed
from pmjev.market.clob import ClobClient
from pmjev.market.gamma import GammaClient, Market
from pmjev.market.live import PolymarketLiveGateway
from pmjev.predictors.deepseek import DeepSeekPredictor, DeepSeekResult
from pmjev.predictors.gbm import gbm_probability, trend_gbm_probability
from pmjev.predictors.jev import JevPredictor, JevResult
from pmjev.resolver import Resolver
from pmjev.risk import LiveRiskGuard, RiskLimits
from pmjev.store import PredictionRecord, StoreBackend, create_store

logger = logging.getLogger(__name__)


def checkpoint_candidates(
    *,
    p_gbm: float,
    p_jev: float | None,
    p_jev_mkt: float | None,
    gbm_trade: bool,
    p_trend_gbm: float,
    trend_gbm_trade: bool,
    jev_trade: bool = True,
    p_deepseek: float | None = None,
    deepseek_trade: bool = False,
    allow_exit: bool = True,
    allow_entry: bool = True,
) -> tuple[list[Candidate], list[Candidate]]:
    """Return models eligible for exit evaluation and for new entries."""

    candidates = [Candidate("gbm", p_gbm), Candidate("trend_gbm", p_trend_gbm)]
    if p_jev is not None:
        candidates.append(Candidate("jev", p_jev))
    if p_jev_mkt is not None:
        candidates.append(Candidate("jev_mkt", p_jev_mkt))
    if p_deepseek is not None:
        candidates.append(Candidate("deepseek", p_deepseek))
    exit_candidates = candidates if allow_exit else []
    entry_enabled = {
        "gbm": gbm_trade,
        "trend_gbm": trend_gbm_trade,
        "jev": jev_trade,
        "jev_mkt": jev_trade,
        "deepseek": deepseek_trade,
    }
    entry_candidates = (
        [
            candidate
            for candidate in candidates
            if entry_enabled.get(candidate.model, True)
        ]
        if allow_entry
        else []
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
        if jev_is_enabled and not (settings.typesafe_api_key or "").strip():
            raise ValueError("TYPESAFE_API_KEY is required for Phase 1; use --no-jev for Phase 0")
        if deepseek_is_enabled and not (settings.openrouter_api_key or "").strip():
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
        )
        if not settings.gbm_trade:
            logger.info("gbm predictions are recorded but gbm does not trade")
        if not settings.trend_gbm_trade:
            logger.info("trend_gbm predictions are recorded but trend_gbm does not trade")
        if deepseek_is_enabled and not settings.deepseek_trade:
            logger.info("deepseek predictions are recorded but deepseek does not trade")
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
            mode=settings.mode,
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
            book_task = self.clob.snapshot(market.up_token, market.down_token)
            feature_task = build_features(
                self.sources[asset.name],
                price_to_beat=price_to_beat,
                chainlink_spot=chainlink_tick.price,
                now=now,
                seconds_remaining=asset.window_seconds - elapsed,
            )
            book, features = await asyncio.gather(book_task, feature_task)
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
            }
            market_state = {
                **blind_state,
                **{
                    key: value
                    for key, value in market_observations.items()
                    if value is not None
                },
            }

            blind = JevResult(None, 0.0, None)
            jev_market: JevResult | None = None
            deepseek = DeepSeekResult(None, 0.0, None, None)
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
                    self.deepseek.predict(
                        blind_state,
                        slug=slug,
                        checkpoint=elapsed,
                    )
                )
                if self.deepseek is not None
                else None
            )
            if jev_task is not None:
                blind, jev_market = await jev_task
            if deepseek_task is not None:
                deepseek = await deepseek_task
            p_gbm = gbm_probability(
                chainlink_tick.price,
                price_to_beat,
                features.sigma_1s,
                asset.window_seconds - elapsed,
            )
            p_trend_gbm = trend_gbm_probability(
                chainlink_tick.price,
                price_to_beat,
                features.sigma_1s,
                asset.window_seconds - elapsed,
                return_10s_pct=float(blind_state["return_10s_pct"]),
                return_30s_pct=float(blind_state["return_30s_pct"]),
                return_60s_pct=float(blind_state["return_60s_pct"]),
                return_5m_pct=float(blind_state["return_5m_pct"]),
                order_flow_buy_ratio_60s=float(blind_state["order_flow_buy_ratio_60s"]),
            )
            latencies = [blind.latency_ms]
            if jev_market is not None:
                latencies.append(jev_market.latency_ms)
            prediction_id = await asyncio.to_thread(
                self.store.add_prediction,
                PredictionRecord(
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
                    p_gbm=p_gbm,
                    jev_latency_ms=max(latencies) if self.jev is not None else None,
                    jev_error=self._jev_error(blind, jev_market),
                    state_json=json.dumps(
                        {"blind": blind_state, "market": market_state},
                        sort_keys=True,
                    ),
                    down_bid=book.down_bid,
                    p_trend_gbm=p_trend_gbm,
                    p_deepseek=deepseek.probability,
                    deepseek_latency_ms=(
                        deepseek.latency_ms if self.deepseek is not None else None
                    ),
                    deepseek_error=deepseek.error,
                    deepseek_provider=deepseek.provider,
                ),
            )
            exit_candidates, entry_candidates = checkpoint_candidates(
                p_gbm=p_gbm,
                p_jev=blind.probability,
                p_jev_mkt=jev_market.probability if jev_market else None,
                gbm_trade=self.settings.gbm_trade,
                p_trend_gbm=p_trend_gbm,
                trend_gbm_trade=self.settings.trend_gbm_trade,
                jev_trade=self.settings.jev_trade,
                p_deepseek=deepseek.probability,
                deepseek_trade=self.settings.deepseek_trade,
                allow_exit=(
                    self.exit_checkpoints is None or elapsed in self.exit_checkpoints
                ),
                allow_entry=(
                    self.entry_checkpoints is None or elapsed in self.entry_checkpoints
                ),
            )
            for candidate in exit_candidates:
                closed_trade = await asyncio.to_thread(
                    self.executor.evaluate_exit,
                    slug=slug,
                    prediction_id=prediction_id,
                    candidate=candidate,
                    up_bid=book.up_bid,
                    down_bid=book.down_bid,
                    fee_rate=market.fee_rate,
                    fee_exponent=market.fee_exponent,
                    spot=chainlink_tick.price,
                    price_to_beat=price_to_beat,
                )
                if closed_trade is not None:
                    self.alerts.trade_exited(asset=asset.name, trade=closed_trade)
            for candidate in entry_candidates:
                opened_trade = await self.executor.execute_async(
                    slug=slug,
                    prediction_id=prediction_id,
                    candidate=candidate,
                    up_ask=book.up_ask,
                    down_ask=book.down_ask,
                    edge=asset.edge,
                    fee_rate=market.fee_rate,
                    fee_exponent=market.fee_exponent,
                    stake_usd=asset.stake_usd,
                    up_token=market.up_token,
                    down_token=market.down_token,
                    reference_timestamp=chainlink_tick.timestamp,
                    spot=chainlink_tick.price,
                    feature_spot=features.feature_spot,
                    price_to_beat=price_to_beat,
                    market_probability_up=market_mid,
                    max_model_market_gap=self.settings.max_model_market_gap,
                )
                if opened_trade is not None:
                    self.alerts.trade_opened(
                        asset=asset.name,
                        model=candidate.model,
                        probability_up=candidate.probability_up,
                        trade=opened_trade,
                    )
            logger.info(
                "slug=%s checkpoint=%s market=%s gbm=%.4f trend_gbm=%.4f "
                "jev=%s jev_mkt=%s deepseek=%s latency_ms=%s deepseek_latency_ms=%s",
                slug,
                elapsed,
                f"{market_mid:.4f}" if market_mid is not None else "missing-mid",
                p_gbm,
                p_trend_gbm,
                blind.probability,
                jev_market.probability if jev_market else None,
                deepseek.probability,
                max(latencies) if self.jev is not None else None,
                deepseek.latency_ms if self.deepseek is not None else None,
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
