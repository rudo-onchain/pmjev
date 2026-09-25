"""Async scheduler and application composition for paper collection."""

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
from pmjev.market.clob import ClobClient
from pmjev.market.gamma import GammaClient, Market
from pmjev.predictors.gbm import gbm_probability
from pmjev.predictors.jev import JevPredictor, JevResult
from pmjev.resolver import Resolver
from pmjev.store import PredictionRecord, Store

logger = logging.getLogger(__name__)


def checkpoint_candidates(
    *,
    p_gbm: float,
    p_jev: float | None,
    p_jev_mkt: float | None,
    gbm_trade: bool,
) -> tuple[list[Candidate], list[Candidate]]:
    """Return models eligible for exit evaluation and for new entries."""

    exit_candidates = [Candidate("gbm", p_gbm)]
    if p_jev is not None:
        exit_candidates.append(Candidate("jev", p_jev))
    if p_jev_mkt is not None:
        exit_candidates.append(Candidate("jev_mkt", p_jev_mkt))
    entry_candidates = [
        candidate
        for candidate in exit_candidates
        if candidate.model != "gbm" or gbm_trade
    ]
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
        jev_is_enabled = settings.jev_enabled and not no_jev
        if jev_is_enabled and not (settings.typesafe_api_key or "").strip():
            raise ValueError("TYPESAFE_API_KEY is required for Phase 1; use --no-jev for Phase 0")
        self.store = Store(settings.db_url)
        self.store.initialize()
        self.http = httpx.AsyncClient(timeout=settings.http_timeout_s)
        self.gamma = GammaClient(self.http, settings.gamma_url)
        self.clob = ClobClient(self.http, settings.clob_url)
        self.chainlink = ChainlinkFeed(
            settings.chainlink_ws_url,
            [asset.chainlink_symbol for asset in self.assets],
            settings.chainlink_topic,
        )
        self.sources = {asset.name: self._feature_source(asset) for asset in self.assets}
        self.executor = Executor(
            settings.mode,
            self.store,
            settings.fee_peak,
            daily_loss_limit_usd=settings.daily_loss_limit_usd,
        )
        if not settings.gbm_trade:
            logger.info("gbm predictions are recorded but gbm does not trade")
        self.jev = (
            JevPredictor(settings.jev_timeout_s, settings.typesafe_api_key)
            if jev_is_enabled
            else None
        )
        self.resolver = Resolver(self.store, self.gamma)
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
        self.chainlink.close()
        for source in self.sources.values():
            source.close()
        await self.http.aclose()
        self.store.close()

    async def _open_asset(
        self, asset: AssetConfig, window_start: int
    ) -> tuple[AssetConfig, Market] | None:
        slug = build_slug(asset, window_start)
        try:
            market = await self.gamma.market(slug)
            expected_topic = {
                30: "crypto_prices_twap_thirty",
                60: "crypto_prices_twap_sixty",
            }[market.twap_lookback_seconds]
            if self.settings.chainlink_topic != expected_topic:
                raise ValueError(
                    f"{slug} requires {expected_topic}, configured {self.settings.chainlink_topic}"
                )
            deadline = time.monotonic() + 2.0
            tick = self.chainlink.price_to_beat(asset.chainlink_symbol, window_start)
            while tick is None and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                tick = self.chainlink.price_to_beat(asset.chainlink_symbol, window_start)
            if tick is None:
                self.store.upsert_window(
                    slug=slug,
                    asset=asset.name,
                    window_start=window_start,
                    up_token=market.up_token,
                    down_token=market.down_token,
                    price_to_beat=None,
                    status="no_open",
                )
                logger.error("%s status=no_open", slug)
                return None
            self.store.upsert_window(
                slug=slug,
                asset=asset.name,
                window_start=window_start,
                up_token=market.up_token,
                down_token=market.down_token,
                price_to_beat=tick.price,
                status="open",
            )
            return asset, market
        except Exception:
            self.store.upsert_window(
                slug=slug,
                asset=asset.name,
                window_start=window_start,
                up_token=None,
                down_token=None,
                price_to_beat=None,
                status="error",
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
    ) -> None:
        slug = market.slug
        try:
            chainlink_tick = self.chainlink.latest(asset.chainlink_symbol)
            if chainlink_tick is None or chainlink_tick.timestamp < time.time() - 10:
                raise RuntimeError("Chainlink feed has no fresh tick")
            window_rows = [row for row in self.store.pending_windows() if row["slug"] == slug]
            if not window_rows or window_rows[0]["price_to_beat"] is None:
                raise RuntimeError("window has no price_to_beat")
            price_to_beat = float(window_rows[0]["price_to_beat"])
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
                (book.up_bid + book.up_ask) / 2 if book.up_bid is not None else None
            )
            market_state = {
                **blind_state,
                "polymarket_up_bid": book.up_bid,
                "polymarket_up_ask": book.up_ask,
                "polymarket_up_mid": market_mid,
            }

            blind = JevResult(None, 0.0, None)
            jev_market: JevResult | None = None
            if self.jev is not None and asset.jev.enabled:
                blind, jev_market = await self.jev.predict_variants(
                    blind_state,
                    market_state
                    if asset.jev.market_variant and self.settings.jev_market_variant
                    else None,
                    slug=slug,
                    checkpoint=elapsed,
                )
            p_gbm = gbm_probability(
                chainlink_tick.price,
                price_to_beat,
                features.sigma_1s,
                asset.window_seconds - elapsed,
            )
            latencies = [blind.latency_ms]
            if jev_market is not None:
                latencies.append(jev_market.latency_ms)
            prediction_id = self.store.add_prediction(
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
                )
            )
            exit_candidates, entry_candidates = checkpoint_candidates(
                p_gbm=p_gbm,
                p_jev=blind.probability,
                p_jev_mkt=jev_market.probability if jev_market else None,
                gbm_trade=self.settings.gbm_trade,
            )
            for candidate in exit_candidates:
                closed_trade = self.executor.evaluate_exit(
                    slug=slug,
                    prediction_id=prediction_id,
                    candidate=candidate,
                    up_bid=book.up_bid,
                    down_bid=book.down_bid,
                    fee_rate=market.fee_rate,
                    fee_exponent=market.fee_exponent,
                )
                if closed_trade is not None:
                    self.alerts.trade_exited(asset=asset.name, trade=closed_trade)
            for candidate in entry_candidates:
                opened_trade = self.executor.execute(
                    slug=slug,
                    prediction_id=prediction_id,
                    candidate=candidate,
                    up_ask=book.up_ask,
                    down_ask=book.down_ask,
                    edge=asset.edge,
                    fee_rate=market.fee_rate,
                    fee_exponent=market.fee_exponent,
                    stake_usd=asset.stake_usd,
                )
                if opened_trade is not None:
                    self.alerts.trade_opened(
                        asset=asset.name,
                        model=candidate.model,
                        probability_up=candidate.probability_up,
                        trade=opened_trade,
                    )
            logger.info(
                "slug=%s checkpoint=%s market=%s gbm=%.4f jev=%s jev_mkt=%s latency_ms=%s",
                slug,
                elapsed,
                f"{market_mid:.4f}" if market_mid is not None else "missing-bid",
                p_gbm,
                blind.probability,
                jev_market.probability if jev_market else None,
                max(latencies) if self.jev is not None else None,
            )
        except Exception:
            logger.exception("checkpoint failed slug=%s elapsed=%s", slug, elapsed)

    async def _run_window(self, assets: list[AssetConfig], window_start: int) -> None:
        opened = await asyncio.gather(*(self._open_asset(asset, window_start) for asset in assets))
        active = [item for item in opened if item is not None]
        schedule = sorted({checkpoint for asset, _ in active for checkpoint in asset.checkpoints})
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
                        timeout=2.0,
                    )
                    for asset, market in active
                    if elapsed in asset.checkpoints
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, TimeoutError):
                    logger.error("checkpoint exceeded 2-second budget elapsed=%s", elapsed)
        resolution_delay = (
            window_start + max(asset.window_seconds for asset, _ in active) + 30 - time.time()
            if active
            else 0
        )
        if resolution_delay > 0:
            await asyncio.sleep(resolution_delay)
        resolved, _ = await self.resolver.resolve_pending_details()
        for resolution in resolved:
            self.alerts.window_settled(slug=resolution.slug, outcome=resolution.outcome)

    async def run_forever(self) -> None:
        if self.settings.mode != "paper":
            # Exercise the explicit stub before starting network workers.
            self.executor.execute(
                slug="startup-check",
                prediction_id=0,
                candidate=Candidate("gbm", 0.5),
                up_ask=0.5,
                down_ask=0.5,
                edge=1.0,
                stake_usd=1.0,
            )
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
            expected_topic = {
                30: "crypto_prices_twap_thirty",
                60: "crypto_prices_twap_sixty",
            }[market.twap_lookback_seconds]
            if runner.settings.chainlink_topic != expected_topic:
                raise ValueError(
                    f"requires {expected_topic}, configured {runner.settings.chainlink_topic}"
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
            return (
                f"{asset.name}: gamma=ok twap={market.twap_lookback_seconds}s "
                f"fee_rate={market.fee_rate:g} "
                f"clob={book.up_bid:.2f}/{book.up_ask:.2f} "
                f"source_spot={features.feature_spot:.6g}"
            ) if book.up_bid is not None else (
                f"{asset.name}: gamma=ok twap={market.twap_lookback_seconds}s "
                f"fee_rate={market.fee_rate:g} clob=missing/{book.up_ask:.2f} "
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
