"""Authenticated live-order and redemption boundary."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from importlib import import_module
from importlib.util import find_spec
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LiveOrderResult:
    order_id: str
    status: str
    spent: float
    size: float
    fill_price: float | None


class LiveOrderGateway(Protocol):
    async def buy_fok(
        self, *, token_id: str, amount_usd: float, max_price: float
    ) -> LiveOrderResult | None: ...

    async def redeem(self, *, condition_id: str) -> str | None: ...

    async def close(self) -> None: ...


class PolymarketLiveGateway:
    """Thin adapter over the official unified ``polymarket-client`` SDK.

    Order placement is never retried. A transport error after submission is
    ambiguous and must be handled by the executor's permanent in-process latch.
    """

    def __init__(
        self,
        *,
        private_key: str,
        wallet: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
    ) -> None:
        if find_spec("polymarket") is None:
            raise RuntimeError(
                "MODE=live requires polymarket-client; reinstall the project dependencies"
            )
        self._private_key = private_key
        self._wallet = wallet
        self._api_key = api_key
        self._api_secret = api_secret
        self._api_passphrase = api_passphrase
        self._client: Any | None = None

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            sdk = import_module("polymarket")
            models = import_module("polymarket.models")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "MODE=live requires the polymarket-client dependency"
            ) from exc
        credentials = models.ApiKeyCreds(
            key=self._api_key,
            secret=self._api_secret,
            passphrase=self._api_passphrase,
        )
        self._client = await sdk.AsyncSecureClient.create(
            private_key=self._private_key,
            wallet=self._wallet,
            credentials=credentials,
        )
        return self._client

    async def buy_fok(
        self, *, token_id: str, amount_usd: float, max_price: float
    ) -> LiveOrderResult | None:
        client = await self._get_client()
        response = await client.place_market_order(
            token_id=token_id,
            side="BUY",
            amount=str(Decimal(str(amount_usd))),
            max_spend=str(Decimal(str(amount_usd))),
            max_price=str(Decimal(str(max_price))),
            order_type="FOK",
        )
        if not bool(response.ok):
            logger.warning(
                "live FOK rejected token=%s code=%s message=%s",
                token_id,
                getattr(response, "code", "unknown"),
                getattr(response, "message", "unknown"),
            )
            return None
        spent = float(response.making_amount)
        size = float(response.taking_amount)
        status = str(response.status)
        fill_price = spent / size if status == "matched" and size > 0 else None
        return LiveOrderResult(
            order_id=str(response.order_id),
            status=status,
            spent=spent,
            size=size,
            fill_price=fill_price,
        )

    async def redeem(self, *, condition_id: str) -> str | None:
        client = await self._get_client()
        handle = await client.redeem_positions(condition_id=condition_id)
        outcome = await handle.wait()
        for name in ("transaction_hash", "tx_hash", "hash"):
            value = getattr(outcome, name, None)
            if value:
                return str(value)
        return None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
