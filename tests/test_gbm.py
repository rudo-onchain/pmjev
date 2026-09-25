from __future__ import annotations

import math

import pytest

from pmjev.predictors.gbm import (
    MAX_TREND_Z_ADJUSTMENT,
    gbm_probability,
    normal_cdf,
    trend_gbm_probability,
)


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


def trend_probability(*, momentum: float, order_flow: float = 0.5) -> float:
    return trend_gbm_probability(
        100.0,
        100.0,
        0.001,
        60.0,
        return_10s_pct=momentum,
        return_30s_pct=momentum,
        return_60s_pct=momentum,
        return_5m_pct=momentum,
        order_flow_buy_ratio_60s=order_flow,
    )


def test_trend_gbm_matches_baseline_without_trend() -> None:
    assert trend_probability(momentum=0.0) == pytest.approx(0.5)


def test_trend_gbm_moves_with_aligned_momentum() -> None:
    assert trend_probability(momentum=1.0) > 0.5
    assert trend_probability(momentum=-1.0) < 0.5


def test_trend_gbm_reduces_conflicting_momentum() -> None:
    aligned = trend_probability(momentum=0.5)
    conflicted = trend_gbm_probability(
        100.0,
        100.0,
        0.001,
        60.0,
        return_10s_pct=0.5,
        return_30s_pct=-0.5,
        return_60s_pct=0.5,
        return_5m_pct=-0.5,
        order_flow_buy_ratio_60s=0.5,
    )

    assert abs(conflicted - 0.5) < abs(aligned - 0.5)


def test_trend_gbm_caps_extreme_adjustment() -> None:
    assert trend_probability(momentum=20.0, order_flow=1.0) == pytest.approx(
        normal_cdf(MAX_TREND_Z_ADJUSTMENT)
    )
