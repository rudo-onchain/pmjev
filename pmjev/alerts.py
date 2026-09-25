"""Compact Telegram alert formatting and delivery scheduling."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from pmjev.store import StoreBackend, TradeRecord

BANGKOK = ZoneInfo("Asia/Bangkok")
MODEL_LABELS = {"jev": "JEV", "jev_mkt": "MKT", "gbm": "GBM", "trend_gbm": "TGBM"}
logger = logging.getLogger(__name__)


def _model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model.upper())


def _signed_usd(value: float, *, cents: bool) -> str:
    precision = 2 if cents else 0
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):.{precision}f}"


def _stake_usd(value: float) -> str:
    return f"${value:.0f}" if value.is_integer() else f"${value:.2f}"


def entry_message(
    *,
    mode: str,
    asset: str,
    model: str,
    side: str,
    price: float,
    stake: float,
    held_probability: float,
) -> str:
    probability = f"{held_probability:.2f}".removeprefix("0")
    return (
        f"🟢 IN | {mode.upper()} {asset.upper()} {_model_label(model)} "
        f"{side.upper()} @{price:.2f}\n"
        f"{_stake_usd(stake)} | p={probability}"
    )


def exit_message(
    *,
    mode: str,
    asset: str,
    model: str,
    side: str,
    entry_price: float,
    exit_price: float,
    pnl: float,
    return_fraction: float,
) -> str:
    return (
        f"🔴 EXIT | {mode.upper()} {asset.upper()} {_model_label(model)} {side.upper()} "
        f"{entry_price:.2f}→{exit_price:.2f}\n"
        f"PnL {_signed_usd(pnl, cents=True)} ({return_fraction:.0%})"
    )


def settlement_message(
    *,
    mode: str,
    asset: str,
    model: str,
    side: str,
    won: bool,
    pnl: float,
    daily_pnl: float,
) -> str:
    icon = "✅" if won else "❌"
    result = "WIN" if won else "LOSS"
    return (
        f"{icon} SET | {mode.upper()} {asset.upper()} {_model_label(model)} "
        f"{side.upper()} {result}\n"
        f"PnL {_signed_usd(pnl, cents=True)} | Day {_signed_usd(daily_pnl, cents=True)}"
    )


def summary_message(*, mode: str, icon: str, label: str, totals: dict[str, float]) -> str:
    jev = totals.get("jev", 0.0)
    market = totals.get("jev_mkt", 0.0)
    gbm = totals.get("gbm", 0.0)
    trend_gbm = totals.get("trend_gbm", 0.0)
    net = sum(totals.values())
    return (
        f"{icon} {mode.upper()} {label} | JEV {_signed_usd(jev, cents=False)} "
        f"| MKT {_signed_usd(market, cents=False)}\n"
        f"GBM {_signed_usd(gbm, cents=False)} | TGBM {_signed_usd(trend_gbm, cents=False)} "
        f"| Net {_signed_usd(net, cents=False)}"
    )


@dataclass(frozen=True, slots=True)
class SummaryPeriod:
    key: str
    icon: str
    label: str
    start: datetime
    end: datetime


def due_summary_periods(now: datetime) -> list[SummaryPeriod]:
    """Return summary periods due at the supplied Bangkok-local time."""

    local = now.astimezone(BANGKOK)
    periods: list[SummaryPeriod] = []
    if local.minute == 2:
        end = local.replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=1)
        periods.append(
            SummaryPeriod(
                key=f"hour:{start.isoformat()}",
                icon="🕐",
                label=f"{start:%H}-{end:%H}h",
                start=start,
                end=end,
            )
        )
    if local.hour == 7 and local.minute == 5:
        end = local.replace(hour=7, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        periods.append(
            SummaryPeriod(
                key=f"day:{start:%Y-%m-%d}",
                icon="📅",
                label=f"{start:%d %b}",
                start=start,
                end=end,
            )
        )
    return periods


class TelegramAlerts:
    """Queue and deliver compact trade alerts without blocking trading work."""

    def __init__(
        self,
        *,
        store: StoreBackend,
        client: httpx.AsyncClient,
        bot_token: str | None,
        chat_id: str | None,
        message_thread_id: int | None = None,
        mode: str = "paper",
        summary_poll_seconds: float = 15.0,
        queue_size: int = 100,
    ) -> None:
        self._store = store
        self._client = client
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._message_thread_id = message_thread_id
        self._mode = mode
        self._summary_poll_seconds = summary_poll_seconds
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=queue_size)
        self._stop = asyncio.Event()
        self._closed = False
        self._sent_periods: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def publish(self, message: str) -> None:
        if not self.enabled or self._closed:
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("telegram alert queue full; dropping message")

    def trade_opened(
        self,
        *,
        asset: str,
        model: str,
        probability_up: float,
        trade: TradeRecord,
    ) -> None:
        held_probability = probability_up if trade.side == "up" else 1.0 - probability_up
        self.publish(
            entry_message(
                mode=trade.mode,
                asset=asset,
                model=model,
                side=trade.side,
                price=trade.price,
                stake=trade.price * trade.size,
                held_probability=held_probability,
            )
        )

    def trade_exited(self, *, asset: str, trade: TradeRecord) -> None:
        if trade.exit_price is None or trade.pnl is None:
            return
        stake = trade.price * trade.size
        self.publish(
            exit_message(
                mode=trade.mode,
                asset=asset,
                model=trade.model,
                side=trade.side,
                entry_price=trade.price,
                exit_price=trade.exit_price,
                pnl=trade.pnl,
                return_fraction=trade.pnl / stake if stake else 0.0,
            )
        )

    async def trade_settled(
        self,
        *,
        mode: str,
        asset: str,
        model: str,
        side: str,
        outcome: int,
        pnl: float,
    ) -> None:
        utc_now = datetime.now(UTC)
        day_start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        totals = await asyncio.to_thread(
            self._store.pnl_by_model, day_start, utc_now.timestamp()
        )
        daily_pnl = sum(totals.values())
        won = (side == "up" and outcome == 1) or (side == "down" and outcome == 0)
        self.publish(
            settlement_message(
                mode=mode,
                asset=asset,
                model=model,
                side=side,
                won=won,
                pnl=pnl,
                daily_pnl=daily_pnl,
            )
        )

    async def window_settled(self, *, slug: str, outcome: int) -> None:
        """Publish settlement alerts for trades still open at resolution."""

        trades = await asyncio.to_thread(self._store.trades_for_slug, slug)
        for trade in trades:
            if trade["exit_price"] is not None or trade["pnl"] is None:
                continue
            await self.trade_settled(
                mode=str(trade["mode"]),
                asset=str(trade["asset"]),
                model=str(trade["model"]),
                side=str(trade["side"]),
                outcome=outcome,
                pnl=float(trade["pnl"]),
            )

    async def run(self) -> None:
        if not self.enabled:
            await self._stop.wait()
            return
        sender = asyncio.create_task(self._send_queued())
        summaries = asyncio.create_task(self._send_summaries())
        try:
            await asyncio.gather(sender, summaries)
        finally:
            sender.cancel()
            summaries.cancel()
            await asyncio.gather(sender, summaries, return_exceptions=True)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self.enabled:
            await self._queue.put(None)

    async def _send_queued(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                if message is None:
                    return
                await self._send(message)
            finally:
                self._queue.task_done()

    async def _send(self, message: str) -> None:
        if self._bot_token is None or self._chat_id is None:
            return
        try:
            payload: dict[str, str | int] = {
                "chat_id": self._chat_id,
                "text": message,
            }
            if self._message_thread_id is not None:
                payload["message_thread_id"] = self._message_thread_id
            response = await self._client.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json=payload,
            )
            if response.status_code >= 400:
                logger.warning("telegram alert failed status=%s", response.status_code)
                return
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                logger.warning("telegram alert returned an unsuccessful response")
        except Exception as exc:
            logger.warning("telegram alert failed error=%s", type(exc).__name__)

    async def _send_summaries(self) -> None:
        while not self._stop.is_set():
            await self._queue_due_summaries(datetime.now(BANGKOK))
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._summary_poll_seconds)

    async def _queue_due_summaries(self, now: datetime) -> None:
        for period in due_summary_periods(now):
            if period.key in self._sent_periods:
                continue
            totals = await asyncio.to_thread(
                self._store.pnl_by_model,
                period.start.timestamp(),
                period.end.timestamp(),
            )
            self.publish(
                summary_message(
                    mode=self._mode,
                    icon=period.icon,
                    label=period.label,
                    totals=totals,
                )
            )
            self._sent_periods.add(period.key)
