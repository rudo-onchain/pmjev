from __future__ import annotations

import math

import pytest

from pmjev.predictors.gbm import gbm_probability


def test_gbm_at_the_money_is_half() -> None:
    assert gbm_probability(100.0, 100.0, 0.001, 60.0) == pytest.approx(0.5)


def test_gbm_matches_spec_formula() -> None:
    spot = 101.0
    strike = 100.0
    sigma = 0.002
    tau = 120.0
    z_score = math.log(spot / strike) / (sigma * math.sqrt(tau))
    expected = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
    assert gbm_probability(spot, strike, sigma, tau) == pytest.approx(expected)


@pytest.mark.parametrize(("spot", "expected"), [(101.0, 1.0), (99.0, 0.0), (100.0, 0.5)])
def test_gbm_zero_volatility_limit(spot: float, expected: float) -> None:
    assert gbm_probability(spot, 100.0, 0.0, 30.0) == expected


def test_gbm_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        gbm_probability(0.0, 100.0, 0.1, 1.0)
