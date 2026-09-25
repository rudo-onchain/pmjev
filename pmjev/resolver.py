"""Resolve closed windows from Gamma outcomes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from pmjev.market.gamma import GammaClient
from pmjev.store import StoreBackend

logger = logging.getLogger(__name__)


class PositionRedeemer(Protocol):
    async def redeem(self, *, condition_id: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ResolvedWindow:
    slug: str
    outcome: int


class Resolver:
    def __init__(
        self,
        store: StoreBackend,
        gamma: GammaClient,
        concurrency: int = 8,
        redeemer: PositionRedeemer | None = None,
    ) -> None:
        self._store = store
        self._gamma = gamma
        self._semaphore = asyncio.Semaphore(concurrency)
        self._redeemer = redeemer

    async def _resolve_one(self, slug: str) -> ResolvedWindow | None:
        async with self._semaphore:
            try:
                outcome = await self._gamma.outcome(slug)
                if outcome is None:
                    return None
                # Gamma outcomePrices are authoritative for the binary outcome. The
                # separate close tick is optional until Chainlink semantics are verified.
                await asyncio.to_thread(
                    self._store.resolve_window,
                    slug,
                    outcome,
                    None,
                )
                return ResolvedWindow(slug=slug, outcome=outcome)
            except Exception:
                logger.exception("failed to resolve %s", slug)
                return None

    async def resolve_pending_details(self) -> tuple[list[ResolvedWindow], int]:
        """Resolve pending windows and return the ones settled by this call."""

        pending = await asyncio.to_thread(self._store.pending_windows)
        results = await asyncio.gather(*(self._resolve_one(str(row["slug"])) for row in pending))
        resolved = [result for result in results if result is not None]
        await self.redeem_pending()
        return resolved, len(results)

    async def redeem_pending(self) -> None:
        """Retry every unresolved live-position redemption on each resolver pass."""

        if self._redeemer is None:
            return
        pending = await asyncio.to_thread(self._store.pending_redemptions)
        for row in pending:
            slug = str(row["slug"])
            condition_id = str(row["condition_id"])
            try:
                await asyncio.to_thread(self._store.mark_redemption, slug, status="pending")
                transaction_hash = await self._redeemer.redeem(condition_id=condition_id)
                await asyncio.to_thread(
                    self._store.mark_redemption,
                    slug,
                    status="redeemed",
                    transaction_hash=transaction_hash,
                )
                logger.warning("LIVE REDEEM slug=%s tx=%s", slug, transaction_hash)
            except Exception:
                await asyncio.to_thread(self._store.mark_redemption, slug, status="error")
                logger.exception("failed to redeem live position for %s", slug)

    async def resolve_pending(self) -> tuple[int, int]:
        resolved, checked = await self.resolve_pending_details()
        return len(resolved), checked
