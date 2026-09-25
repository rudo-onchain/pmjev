"""Driftless geometric-Brownian-motion baseline."""

from __future__ import annotations

import math

MOMENTUM_SPECS = (
    (10.0, 0.35),
    (30.0, 0.30),
    (60.0, 0.25),
    (300.0, 0.10),
)
MAX_TREND_Z_ADJUSTMENT = 0.75


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def gbm_probability(spot: float, strike: float, sigma_1s: float, tau_s: float) -> float:
    """Compute Phi(log(S/K) / (sigma * sqrt(tau))) exactly as specified."""

    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if sigma_1s < 0 or tau_s < 0:
        raise ValueError("sigma and tau cannot be negative")
    if tau_s == 0 or sigma_1s == 0:
        if spot > strike:
            return 1.0
        if spot < strike:
            return 0.0
        return 0.5
    z_score = math.log(spot / strike) / (sigma_1s * math.sqrt(tau_s))
    return normal_cdf(z_score)


def trend_gbm_probability(
    spot: float,
    strike: float,
    sigma_1s: float,
    tau_s: float,
    *,
    return_10s_pct: float,
    return_30s_pct: float,
    return_60s_pct: float,
    return_5m_pct: float,
    order_flow_buy_ratio_60s: float,
) -> float:
    """Return GBM probability with a conservative, bounded trend adjustment.

    Momentum at four horizons is normalized by realized volatility. Agreement
    between horizons controls how much of that signal survives, while 60-second
    order flow supplies a small confirmation. The combined adjustment can move
    the baseline z-score by at most ``MAX_TREND_Z_ADJUSTMENT``.
    """

    baseline = gbm_probability(spot, strike, sigma_1s, tau_s)
    if sigma_1s == 0 or tau_s == 0:
        return baseline
    if not 0.0 <= order_flow_buy_ratio_60s <= 1.0:
        raise ValueError("order flow buy ratio must be between zero and one")

    returns = (return_10s_pct, return_30s_pct, return_60s_pct, return_5m_pct)
    if any(value <= -100.0 for value in returns):
        raise ValueError("returns must be greater than -100 percent")

    normalized_scores: list[tuple[float, float]] = []
    for (horizon_s, weight), return_pct in zip(MOMENTUM_SPECS, returns, strict=True):
        log_return = math.log1p(return_pct / 100.0)
        score = log_return / (sigma_1s * math.sqrt(horizon_s))
        normalized_scores.append((max(-3.0, min(3.0, score)), weight))

    momentum_score = sum(score * weight for score, weight in normalized_scores)
    direction_score = sum(
        (1.0 if score > 0 else -1.0 if score < 0 else 0.0) * weight
        for score, weight in normalized_scores
    )
    agreement = abs(direction_score)
    momentum_adjustment = 0.25 * momentum_score * agreement
    order_flow_adjustment = 0.10 * (2.0 * order_flow_buy_ratio_60s - 1.0)
    trend_adjustment = max(
        -MAX_TREND_Z_ADJUSTMENT,
        min(MAX_TREND_Z_ADJUSTMENT, momentum_adjustment + order_flow_adjustment),
    )

    baseline_z = math.log(spot / strike) / (sigma_1s * math.sqrt(tau_s))
    return normal_cdf(baseline_z + trend_adjustment)
