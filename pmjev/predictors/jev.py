"""Jev adapter using the required langchain-typesafe API."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pmjev.executor import TradeAction

logger = logging.getLogger(__name__)

QUESTION = (
    "When this 5-minute window closes, the price will be >= price_to_beat, "
    "so the market resolves Up."
)
ACTION_QUESTION = (
    "Choose the trading action this model recommends at this checkpoint using only the "
    "supplied state. Choose skip when the evidence is weak, conflicting, or insufficient."
)
ACTION_CRITERIA: dict[str, Any] = {
    "buy_up": "Recommend buying Up because Up is the best-supported trade.",
    "buy_down": "Recommend buying Down because Down is the best-supported trade.",
    "skip": "Recommend no trade because neither side has a sufficiently strong case.",
}


@dataclass(frozen=True, slots=True)
class JevResult:
    probability: float | None
    action: TradeAction | None
    latency_ms: float
    error: str | None


class AsyncClassifier(Protocol):
    async def ainvoke(self, input: Any, config: Any | None = None, **kwargs: Any) -> Any: ...


class JevPredictor:
    def __init__(
        self,
        timeout_s: float,
        api_key: str | None = None,
        classifier: AsyncClassifier | None = None,
    ) -> None:
        if classifier is not None:
            self._classifier = classifier
        else:
            from langchain_typesafe import TypeSafeClassifier

            if api_key:
                self._classifier = TypeSafeClassifier(model="jev-latest", api_key=api_key)
            else:
                self._classifier = TypeSafeClassifier(model="jev-latest")
        self._timeout_s = timeout_s
        logger.info("jev ready model=jev-latest timeout_s=%s", timeout_s)

    async def _predict_one(
        self,
        state: dict[str, Any],
        *,
        variant: str,
        slug: str,
        checkpoint: int | None,
    ) -> JevResult:
        from langchain_typesafe import Choice, Noul

        started = time.perf_counter()
        logger.info(
            "jev request start slug=%s checkpoint=%s variant=%s",
            slug,
            checkpoint,
            variant,
        )
        try:
            response = await asyncio.wait_for(
                self._classifier.ainvoke(
                    {
                        "state": state,
                        "questions": {
                            "up": Noul(instructions=QUESTION),
                            "trade_action": Choice(
                                instructions=ACTION_QUESTION,
                                criteria=ACTION_CRITERIA,
                            ),
                        },
                    }
                ),
                timeout=self._timeout_s,
            )
            probability = float(response.nouls["up"].noul)
            if not 0 <= probability <= 1:
                raise ValueError(f"Jev returned out-of-range probability {probability}")
            action = str(response.choices["trade_action"].choice)
            if action not in {"buy_up", "buy_down", "skip"}:
                raise ValueError(f"Jev returned unknown trade action {action!r}")
            latency_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "jev request done slug=%s checkpoint=%s variant=%s "
                "probability=%.4f action=%s latency_ms=%.0f",
                slug,
                checkpoint,
                variant,
                probability,
                action,
                latency_ms,
            )
            return JevResult(
                probability=probability,
                action=cast(TradeAction, action),
                latency_ms=latency_ms,
                error=None,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "jev request failed slug=%s checkpoint=%s variant=%s latency_ms=%.0f error=%s",
                slug,
                checkpoint,
                variant,
                latency_ms,
                error,
            )
            return JevResult(
                probability=None,
                action=None,
                latency_ms=latency_ms,
                error=error,
            )

    async def predict_variants(
        self,
        blind_state: dict[str, Any],
        market_state: dict[str, Any] | None,
        *,
        slug: str = "",
        checkpoint: int | None = None,
    ) -> tuple[JevResult, JevResult | None]:
        """Run blind and market-visible requests concurrently, once, with no retry."""

        if market_state is None:
            return (
                await self._predict_one(
                    blind_state, variant="blind", slug=slug, checkpoint=checkpoint
                ),
                None,
            )
        blind, market = await asyncio.gather(
            self._predict_one(blind_state, variant="blind", slug=slug, checkpoint=checkpoint),
            self._predict_one(market_state, variant="market", slug=slug, checkpoint=checkpoint),
        )
        return blind, market
