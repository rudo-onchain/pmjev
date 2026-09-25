"""Resolve closed windows from Gamma outcomes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from pmjev.market.gamma import GammaClient
from pmjev.store import Store

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedWindow:
    slug: str
    outcome: int


class Resolver:
    def __init__(self, store: Store, gamma: GammaClient, concurrency: int = 8) -> None:
        self._store = store
        self._gamma = gamma
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _resolve_one(self, slug: str) -> ResolvedWindow | None:
        async with self._semaphore:
            try:
                outcome = await self._gamma.outcome(slug)
                if outcome is None:
                    return None
                # Gamma outcomePrices are authoritative for the binary outcome. The
                # separate close tick is optional until Chainlink semantics are verified.
                self._store.mark_resolved(slug, outcome, close_price=None)
                self._store.settle_trades(slug, outcome)
                return ResolvedWindow(slug=slug, outcome=outcome)
            except Exception:
                logger.exception("failed to resolve %s", slug)
                return None

    async def resolve_pending_details(self) -> tuple[list[ResolvedWindow], int]:
        """Resolve pending windows and return the ones settled by this call."""

        pending = self._store.pending_windows()
        results = await asyncio.gather(*(self._resolve_one(str(row["slug"])) for row in pending))
        return [result for result in results if result is not None], len(results)

    async def resolve_pending(self) -> tuple[int, int]:
        resolved, checked = await self.resolve_pending_details()
        return len(resolved), checked
