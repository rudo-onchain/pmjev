"""OpenRouter adapter for direct, paper-only DeepSeek trade decisions."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import httpx

from pmjev.executor import fee_per_share
from pmjev.features import Kline10s

logger = logging.getLogger(__name__)

DirectAction = Literal["buy_up", "buy_down", "skip"]

SYSTEM_PROMPT = (
    "You are making one paper-trade decision for a five-minute crypto binary market. "
    "Choose buy_up, buy_down, or skip to maximize expected profit after the supplied "
    "taker fees. A less likely side can still be a valid buy when its ask is cheap enough. "
    "Use the 10-second OHLCV/order-flow bars, reference prices, time remaining, and both "
    "sides of the market. Return a calibrated p_up and only the requested structured output."
)

DECISION_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "five_minute_direct_trade_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["buy_up", "buy_down", "skip"],
                },
                "p_up": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["action", "p_up"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True, slots=True)
class DirectMarketContext:
    chainlink_spot: float
    feature_spot: float
    price_to_beat: float
    seconds_remaining: int
    up_bid: float | None
    up_ask: float | None
    down_bid: float | None
    down_ask: float | None
    fee_rate: float
    fee_exponent: int


@dataclass(frozen=True, slots=True)
class DeepSeekDirectResult:
    action: DirectAction | None
    probability_up: float | None
    latency_ms: float
    error: str | None
    provider: str | None


def _fee(price: float | None, rate: float, exponent: int) -> float | None:
    return fee_per_share(price, rate, exponent) if price is not None else None


def _request_payload(
    klines: Sequence[Kline10s], context: DirectMarketContext
) -> dict[str, Any]:
    first_start = klines[0].start if klines else 0.0
    bars = [
        {
            "offset_s": int(bar.start - first_start),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "buy_volume_ratio": bar.buy_volume_ratio,
        }
        for bar in klines
    ]
    return {
        "market_rule": (
            "Up wins when the official closing price is greater than or equal to "
            "price_to_beat; otherwise Down wins."
        ),
        "market": {
            "chainlink_spot": context.chainlink_spot,
            "feature_spot": context.feature_spot,
            "price_to_beat": context.price_to_beat,
            "seconds_remaining": context.seconds_remaining,
            "up_bid": context.up_bid,
            "up_ask": context.up_ask,
            "down_bid": context.down_bid,
            "down_ask": context.down_ask,
            "up_fee_per_share": _fee(
                context.up_ask, context.fee_rate, context.fee_exponent
            ),
            "down_fee_per_share": _fee(
                context.down_ask, context.fee_rate, context.fee_exponent
            ),
            "fee_rate": context.fee_rate,
            "fee_exponent": context.fee_exponent,
        },
        "klines_10s": bars,
    }


class DeepSeekDirectPredictor:
    """Ask a pinned DeepSeek model for a direct paper-trade action."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        model: str,
        url: str,
        timeout_s: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model
        self._url = url
        self._timeout_s = timeout_s
        logger.info("deepseek_direct ready model=%s timeout_s=%s mode=paper", model, timeout_s)

    async def predict(
        self,
        klines: Sequence[Kline10s],
        context: DirectMarketContext,
        *,
        slug: str = "",
        checkpoint: int | None = None,
    ) -> DeepSeekDirectResult:
        started = time.perf_counter()
        logger.info(
            "deepseek_direct request start slug=%s checkpoint=%s model=%s",
            slug,
            checkpoint,
            self._model,
        )
        try:
            response = await self._client.post(
                self._url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "X-OpenRouter-Title": "pmjev",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                _request_payload(klines, context),
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": 48,
                    "reasoning": {"enabled": False},
                    "response_format": DECISION_SCHEMA,
                    "provider": {
                        "sort": "latency",
                        "require_parameters": True,
                        "data_collection": "deny",
                    },
                },
                timeout=self._timeout_s,
            )
            response.raise_for_status()
            payload = response.json()
            choice = payload["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("DeepSeek direct response truncated (finish_reason=length)")
            parsed = json.loads(choice["message"]["content"])
            action = str(parsed["action"])
            if action not in {"buy_up", "buy_down", "skip"}:
                raise ValueError(f"DeepSeek direct returned unknown action {action!r}")
            probability = float(parsed["p_up"])
            if not 0 <= probability <= 1:
                raise ValueError(
                    f"DeepSeek direct returned out-of-range probability {probability}"
                )
            latency_ms = (time.perf_counter() - started) * 1000
            provider = str(payload["provider"]) if payload.get("provider") else None
            logger.info(
                "deepseek_direct request done slug=%s checkpoint=%s action=%s "
                "probability=%.4f latency_ms=%.0f provider=%s",
                slug,
                checkpoint,
                action,
                probability,
                latency_ms,
                provider or "unknown",
            )
            return DeepSeekDirectResult(
                action=cast(DirectAction, action),
                probability_up=probability,
                latency_ms=latency_ms,
                error=None,
                provider=provider,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "deepseek_direct request failed slug=%s checkpoint=%s latency_ms=%.0f "
                "error=%s",
                slug,
                checkpoint,
                latency_ms,
                error,
            )
            return DeepSeekDirectResult(None, None, latency_ms, error, None)
