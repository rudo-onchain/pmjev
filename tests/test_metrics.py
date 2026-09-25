from __future__ import annotations

import math

import pytest

from pmjev.report import brier_score, log_loss, paired_bootstrap_ci, percentile


def test_brier_score() -> None:
    assert brier_score(0.8, 1) == pytest.approx(0.04)
    assert brier_score(0.8, 0) == pytest.approx(0.64)


def test_log_loss() -> None:
    assert log_loss(0.8, 1) == pytest.approx(-math.log(0.8))
    assert log_loss(0.8, 0) == pytest.approx(-math.log(0.2))


def test_log_loss_clips_extremes() -> None:
    assert math.isfinite(log_loss(0.0, 1))
    assert math.isfinite(log_loss(1.0, 0))


def test_percentile_interpolates() -> None:
    assert percentile([0.0, 10.0], 0.95) == pytest.approx(9.5)


def test_paired_bootstrap_preserves_pairs() -> None:
    ci = paired_bootstrap_ci([0.1, 0.2, 0.3], [0.4, 0.5, 0.6], seed=1)
    assert ci is not None
    assert ci[0] == pytest.approx(-0.3)
    assert ci[1] == pytest.approx(-0.3)


def test_empty_bootstrap_has_no_interval() -> None:
    assert paired_bootstrap_ci([], []) is None
