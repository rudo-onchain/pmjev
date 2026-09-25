"""Gamma API market discovery and outcome parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class Market:
    slug: str
    up_token: str
    down_token: str
    fee_rate: float
    fee_exponent: int
    twap_lookback_seconds: int
    condition_id: str | None = None


def _as_list(value: object) -> list[Any]:
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, list) else []
    return value if isinstance(value, list) else []


def _first_market(event: dict[str, Any]) -> dict[str, Any]:
    markets = event.get("markets")
    if isinstance(markets, list) and markets and isinstance(markets[0], dict):
        return markets[0]
    return event


def parse_market(event: dict[str, Any], slug: str) -> Market:
    market = _first_market(event)
    outcomes = [str(value).lower() for value in _as_list(market.get("outcomes"))]
    token_ids = [str(value) for value in _as_list(market.get("clobTokenIds"))]
    if len(outcomes) != len(token_ids) or "up" not in outcomes or "down" not in outcomes:
        raise ValueError(f"Gamma event {slug} has unexpected outcomes/token ids")
    fees_enabled = bool(market.get("feesEnabled", False))
    fee_schedule = market.get("feeSchedule")
    if fees_enabled and not isinstance(fee_schedule, dict):
        raise ValueError(f"Gamma event {slug} enables fees without feeSchedule")
    parsed_fee_schedule: dict[str, Any] = fee_schedule if isinstance(fee_schedule, dict) else {}
    crypto_config = market.get("cryptoMarketConfig")
    if not isinstance(crypto_config, dict):
        raise ValueError(f"Gamma event {slug} has no cryptoMarketConfig")
    twap_seconds = int(crypto_config.get("twapLookbackSeconds", 0))
    if twap_seconds not in (30, 60):
        raise ValueError(f"Gamma event {slug} has unsupported TWAP window {twap_seconds}")
    return Market(
        slug=slug,
        up_token=token_ids[outcomes.index("up")],
        down_token=token_ids[outcomes.index("down")],
        fee_rate=float(parsed_fee_schedule.get("rate", 0.0)) if fees_enabled else 0.0,
        fee_exponent=int(parsed_fee_schedule.get("exponent", 1)) if fees_enabled else 1,
        twap_lookback_seconds=twap_seconds,
        condition_id=(
            str(market["conditionId"])
            if market.get("conditionId")
            else str(event["conditionId"])
            if event.get("conditionId")
            else None
        ),
    )


def parse_outcome(event: dict[str, Any]) -> int | None:
    """Return 1 for Up, 0 for Down, or None while unresolved."""

    market = _first_market(event)
    if not bool(market.get("closed", event.get("closed", False))):
        return None
    outcomes = [str(value).lower() for value in _as_list(market.get("outcomes"))]
    prices = [float(value) for value in _as_list(market.get("outcomePrices"))]
    if len(outcomes) != len(prices) or "up" not in outcomes or "down" not in outcomes:
        raise ValueError("Closed Gamma event has malformed outcomePrices")
    up_price = prices[outcomes.index("up")]
    down_price = prices[outcomes.index("down")]
    if up_price == 1.0 and down_price == 0.0:
        return 1
    if up_price == 0.0 and down_price == 1.0:
        return 0
    raise ValueError(f"Closed Gamma event is not settled: prices={prices}")


class GammaClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def event(self, slug: str) -> dict[str, Any] | None:
        response = await self._client.get(f"{self._base_url}/events", params={"slug": slug})
        response.raise_for_status()
        payload: list[dict[str, Any]] = response.json()
        return payload[0] if payload else None

    async def market(self, slug: str) -> Market:
        event = await self.event(slug)
        if event is None:
            raise LookupError(f"Gamma returned no event for {slug}")
        return parse_market(event, slug)

    async def outcome(self, slug: str) -> int | None:
        event = await self.event(slug)
        if event is None:
            raise LookupError(f"Gamma returned no event for {slug}")
        return parse_outcome(event)
