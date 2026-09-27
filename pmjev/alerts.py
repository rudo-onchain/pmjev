"""Compact Telegram trade-event alert formatting and delivery."""

from __future__ import annotations

import asyncio
import logging

import httpx

from pmjev.store import StoreBackend, TradeRecord

MODEL_LABELS = {
    "jev": "JEV",
    "jev_mkt": "MKT",
    "deepseek": "DS",
    "deepseek_direct": "DSD",
    "gbm": "GBM",
    "trend_gbm": "TGBM",
    "naive_spot": "NAIVE",
}
logger = logging.getLogger(__name__)


def _model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model.upper())


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
) -> str:
    return (
        f"🔴 EXIT | {mode.upper()} {asset.upper()} {_model_label(model)} {side.upper()} "
        f"{entry_price:.2f}→{exit_price:.2f}"
    )


def settlement_message(
    *,
    mode: str,
    asset: str,
    model: str,
    side: str,
    won: bool,
) -> str:
    icon = "✅" if won else "❌"
    result = "WIN" if won else "LOSS"
    return (
        f"{icon} SET | {mode.upper()} {asset.upper()} {_model_label(model)} "
        f"{side.upper()} {result}"
    )


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
        queue_size: int = 100,
    ) -> None:
        self._store = store
        self._client = client
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._message_thread_id = message_thread_id
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=queue_size)
        self._stop = asyncio.Event()
        self._closed = False

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
        if trade.exit_price is None:
            return
        self.publish(
            exit_message(
                mode=trade.mode,
                asset=asset,
                model=trade.model,
                side=trade.side,
                entry_price=trade.price,
                exit_price=trade.exit_price,
            )
        )

    def trade_settled(
        self,
        *,
        mode: str,
        asset: str,
        model: str,
        side: str,
        outcome: int,
    ) -> None:
        won = (side == "up" and outcome == 1) or (side == "down" and outcome == 0)
        self.publish(
            settlement_message(
                mode=mode,
                asset=asset,
                model=model,
                side=side,
                won=won,
            )
        )

    async def window_settled(self, *, slug: str, outcome: int) -> None:
        """Publish settlement alerts for trades still open at resolution."""

        trades = await asyncio.to_thread(self._store.trades_for_slug, slug)
        for trade in trades:
            if trade["exit_price"] is not None or trade["pnl"] is None:
                continue
            self.trade_settled(
                mode=str(trade["mode"]),
                asset=str(trade["asset"]),
                model=str(trade["model"]),
                side=str(trade["side"]),
                outcome=outcome,
            )

    async def run(self) -> None:
        if not self.enabled:
            await self._stop.wait()
            return
        await self._send_queued()

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
