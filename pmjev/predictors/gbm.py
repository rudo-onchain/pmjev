"""Driftless geometric-Brownian-motion baseline."""

from __future__ import annotations

import math


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
