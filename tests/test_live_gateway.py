from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pmjev.market.live import PolymarketLiveGateway


class FakeSdkClient:
    def __init__(self) -> None:
        self.order_kwargs: dict[str, Any] | None = None
        self.redeemed: str | None = None
        self.closed = False

    async def place_market_order(self, **kwargs: Any) -> Any:
        self.order_kwargs = kwargs
        return SimpleNamespace(
            ok=True,
            order_id="order-1",
            status="matched",
            making_amount="9.80",
            taking_amount="20",
        )

    async def redeem_positions(self, *, condition_id: str) -> Any:
        self.redeemed = condition_id

        class Handle:
            async def wait(self) -> Any:
                return SimpleNamespace(transaction_hash="0xtx")

        return Handle()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_live_gateway_uses_official_fok_price_and_spend_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSdkClient()

    class AsyncSecureClient:
        @classmethod
        async def create(cls, **_kwargs: Any) -> FakeSdkClient:
            return client

    sdk = SimpleNamespace(AsyncSecureClient=AsyncSecureClient)
    models = SimpleNamespace(ApiKeyCreds=lambda **kwargs: kwargs)
    monkeypatch.setattr("pmjev.market.live.find_spec", lambda _name: object())
    monkeypatch.setattr(
        "pmjev.market.live.import_module",
        lambda name: models if name == "polymarket.models" else sdk,
    )
    gateway = PolymarketLiveGateway(
        private_key="private",
        wallet="0xwallet",
        api_key="key",
        api_secret="secret",
        api_passphrase="pass",
    )

    result = await gateway.buy_fok(token_id="token", amount_usd=10, max_price=0.5)

    assert result is not None
    assert result.fill_price == pytest.approx(0.49)
    assert client.order_kwargs == {
        "token_id": "token",
        "side": "BUY",
        "amount": "10",
        "max_spend": "10",
        "max_price": "0.5",
        "order_type": "FOK",
    }
    assert await gateway.redeem(condition_id="0xcondition") == "0xtx"
    assert client.redeemed == "0xcondition"
    await gateway.close()
    assert client.closed is True
