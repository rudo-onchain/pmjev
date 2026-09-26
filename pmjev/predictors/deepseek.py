"""OpenRouter adapter for DeepSeek paper-trading predictions."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a calibrated binary forecaster for a five-minute crypto market. "
    "Using only the supplied numeric state, estimate the probability that the official "
    "reference price at the end of the window will be greater than or equal to "
    "price_to_beat. Return only the requested structured output."
)

PROBABILITY_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "five_minute_market_prediction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "p_up": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                }
            },
            "required": ["p_up"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True, slots=True)
class DeepSeekResult:
    probability: float | None
    latency_ms: float
    error: str | None
    provider: str | None


class DeepSeekPredictor:
    """Return a bounded P(Up) from a pinned DeepSeek model on OpenRouter."""

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
        logger.info("deepseek ready model=%s timeout_s=%s mode=paper", model, timeout_s)

    async def predict(
        self,
        state: dict[str, Any],
        *,
        slug: str = "",
        checkpoint: int | None = None,
    ) -> DeepSeekResult:
        started = time.perf_counter()
        logger.info(
            "deepseek request start slug=%s checkpoint=%s model=%s",
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
                            "content": json.dumps(state, sort_keys=True, separators=(",", ":")),
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": 32,
                    "reasoning": {"enabled": False},
                    "response_format": PROBABILITY_SCHEMA,
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
            finish_reason = choice.get("finish_reason")
            if finish_reason == "length":
                raise ValueError(
                    "DeepSeek response truncated (finish_reason=length)"
                )
            content = choice["message"]["content"]
            parsed = json.loads(content)
            probability = float(parsed["p_up"])
            if not 0 <= probability <= 1:
                raise ValueError(f"DeepSeek returned out-of-range probability {probability}")
            latency_ms = (time.perf_counter() - started) * 1000
            provider = str(payload["provider"]) if payload.get("provider") else None
            logger.info(
                "deepseek request done slug=%s checkpoint=%s probability=%.4f "
                "latency_ms=%.0f provider=%s",
                slug,
                checkpoint,
                probability,
                latency_ms,
                provider or "unknown",
            )
            return DeepSeekResult(probability, latency_ms, None, provider)
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "deepseek request failed slug=%s checkpoint=%s latency_ms=%.0f error=%s",
                slug,
                checkpoint,
                latency_ms,
                error,
            )
            return DeepSeekResult(None, latency_ms, error, None)
