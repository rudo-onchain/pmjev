from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from pmjev.predictors.jev import JevPredictor


class FakeClassifier:
    def __init__(self, delay: float, probability: float = 0.7) -> None:
        self.delay = delay
        self.probability = probability
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def ainvoke(self, request: dict[str, Any]) -> Any:
        self.calls += 1
        assert set(request["questions"]) == {"up"}
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            return SimpleNamespace(nouls={"up": SimpleNamespace(noul=self.probability)})
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_variants_run_concurrently() -> None:
    classifier = FakeClassifier(delay=0.05)
    predictor = JevPredictor(timeout_s=0.5, classifier=classifier)
    blind, market = await predictor.predict_variants({"spot": 1}, {"spot": 1, "mid": 0.5})
    assert blind.probability == pytest.approx(0.7)
    assert market is not None and market.probability == pytest.approx(0.7)
    assert classifier.calls == 2
    assert classifier.max_active == 2


@pytest.mark.asyncio
async def test_timeout_is_recorded_without_retry() -> None:
    classifier = FakeClassifier(delay=0.05)
    predictor = JevPredictor(timeout_s=0.001, classifier=classifier)
    blind, market = await predictor.predict_variants({}, {})
    assert blind.probability is None
    assert blind.error is not None and "TimeoutError" in blind.error
    assert market is not None and market.probability is None
    assert classifier.calls == 2


@pytest.mark.asyncio
async def test_request_logs_outcome(caplog: pytest.LogCaptureFixture) -> None:
    classifier = FakeClassifier(delay=0)
    predictor = JevPredictor(timeout_s=0.5, classifier=classifier)
    with caplog.at_level(logging.INFO, logger="pmjev.predictors.jev"):
        await predictor.predict_variants({"spot": 1}, None, slug="eth-updown-5m-1", checkpoint=60)
    assert "jev request start slug=eth-updown-5m-1 checkpoint=60 variant=blind" in caplog.text
    assert "variant=blind probability=0.7000" in caplog.text
