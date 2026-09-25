import logging
from pathlib import Path
from typing import Any

import pytest

import pmjev.__main__ as cli
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


@pytest.mark.parametrize(
    ("elapsed", "allow_exit", "allow_entry"),
    [
        (60, False, False),
        (150, False, True),
        (240, True, True),
        (280, True, False),
    ],
)
def test_checkpoint_actions_are_independent(
    elapsed: int, allow_exit: bool, allow_entry: bool
) -> None:
    exit_candidates, entry_candidates = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=0.30,
        p_jev_mkt=0.35,
        gbm_trade=True,
        allow_exit=allow_exit,
        allow_entry=allow_entry,
    )

    assert bool(exit_candidates) is allow_exit, elapsed
    assert bool(entry_candidates) is allow_entry, elapsed


def test_control_c_stops_cli_without_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def interrupt(coroutine: Any) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr("sys.argv", ["pmjev", "run", "--no-jev"])
    monkeypatch.setattr(cli.asyncio, "run", interrupt)

    with caplog.at_level(logging.INFO, logger="pmjev.__main__"):
        cli.main()

    assert "collector stopped by user" in caplog.text
