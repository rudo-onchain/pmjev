"""Resolve closed windows from Gamma outcomes."""

from __future__ import annotations

import asyncio
import logging

from pmjev.market.gamma import GammaClient
from pmjev.store import Store

logger = logging.getLogger(__name__)


class Resolver:
    def __init__(self, store: Store, gamma: GammaClient, concurrency: int = 8) -> None:
        self._store = store
        self._gamma = gamma
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _resolve_one(self, slug: str) -> bool:
        async with self._semaphore:
            try:
                outcome = await self._gamma.outcome(slug)
                if outcome is None:
                    return False
                # Gamma outcomePrices are authoritative for the binary outcome. The
                # separate close tick is optional until Chainlink semantics are verified.
                self._store.mark_resolved(slug, outcome, close_price=None)
                self._store.settle_trades(slug, outcome)
                return True
            except Exception:
                logger.exception("failed to resolve %s", slug)
                return False

    async def resolve_pending(self) -> tuple[int, int]:
        pending = self._store.pending_windows()
        results = await asyncio.gather(*(self._resolve_one(str(row["slug"])) for row in pending))
        return sum(results), len(results)
