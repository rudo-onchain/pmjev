from pathlib import Path

import pytest

from pmjev.config import Settings
from pmjev.main import PaperRunner, checkpoint_candidates


def test_phase_one_requires_typesafe_api_key() -> None:
    settings = Settings(
        assets_file=Path("assets.yaml"),
        db_url="sqlite:///:memory:",
        typesafe_api_key="",
    )

    with pytest.raises(ValueError, match="TYPESAFE_API_KEY is required"):
        PaperRunner(settings, no_jev=False)


def test_gbm_trade_flag_blocks_entry_but_not_exit_evaluation() -> None:
    exit_candidates, entry_candidates = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=None,
        p_jev_mkt=None,
        gbm_trade=False,
    )

    assert [candidate.model for candidate in exit_candidates] == ["gbm"]
    assert entry_candidates == []
