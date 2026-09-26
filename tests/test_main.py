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


def test_deepseek_requires_openrouter_api_key() -> None:
    settings = Settings(
        _env_file=None,
        assets_file=Path("assets.yaml"),
        db_url="sqlite:///:memory:",
        jev_enabled=False,
        deepseek_enabled=True,
        openrouter_api_key="",
    )

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        PaperRunner(settings, no_jev=False)


def test_gbm_trade_flag_blocks_entry_but_not_exit_evaluation() -> None:
    exit_candidates, entry_candidates = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=None,
        p_jev_mkt=None,
        gbm_trade=False,
        p_trend_gbm=0.62,
        trend_gbm_trade=False,
    )

    assert [candidate.model for candidate in exit_candidates] == ["gbm", "trend_gbm"]
    assert entry_candidates == []


def test_trend_gbm_trade_false_keeps_probability_out_of_entries() -> None:
    exit_candidates, entry_candidates = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=0.30,
        p_jev_mkt=0.35,
        gbm_trade=True,
        p_trend_gbm=0.62,
        trend_gbm_trade=False,
        allow_exit=True,
        allow_entry=True,
    )

    assert [candidate.model for candidate in exit_candidates] == [
        "gbm",
        "trend_gbm",
        "jev",
        "jev_mkt",
    ]
    assert [candidate.model for candidate in entry_candidates] == ["gbm", "jev", "jev_mkt"]
    trend_exit = next(candidate for candidate in exit_candidates if candidate.model == "trend_gbm")
    assert trend_exit.probability_up == 0.62


def test_jev_trade_false_keeps_prediction_for_exit_but_blocks_entry() -> None:
    exit_candidates, entry_candidates = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=0.35,
        p_jev_mkt=None,
        gbm_trade=False,
        p_trend_gbm=0.62,
        trend_gbm_trade=False,
        jev_trade=False,
    )

    assert [candidate.model for candidate in exit_candidates] == [
        "gbm",
        "trend_gbm",
        "jev",
    ]
    assert entry_candidates == []


def test_deepseek_prediction_only_and_paper_trade_flags_are_independent() -> None:
    exits, blocked = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=None,
        p_jev_mkt=None,
        gbm_trade=False,
        p_trend_gbm=0.62,
        trend_gbm_trade=False,
        p_deepseek=0.80,
        deepseek_trade=False,
    )
    _, enabled = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=None,
        p_jev_mkt=None,
        gbm_trade=False,
        p_trend_gbm=0.62,
        trend_gbm_trade=False,
        p_deepseek=0.80,
        deepseek_trade=True,
    )

    assert [candidate.model for candidate in exits] == ["gbm", "trend_gbm", "deepseek"]
    assert blocked == []
    assert [candidate.model for candidate in enabled] == ["deepseek"]


def test_trend_gbm_trade_true_enters_only_at_entry_checkpoints() -> None:
    _, blocked = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=0.30,
        p_jev_mkt=None,
        gbm_trade=False,
        p_trend_gbm=0.80,
        trend_gbm_trade=True,
        allow_exit=False,
        allow_entry=False,
    )
    _, opened = checkpoint_candidates(
        p_gbm=0.25,
        p_jev=0.30,
        p_jev_mkt=None,
        gbm_trade=False,
        p_trend_gbm=0.80,
        trend_gbm_trade=True,
        allow_exit=True,
        allow_entry=True,
    )

    assert blocked == []
    assert [(candidate.model, candidate.probability_up) for candidate in opened] == [
        ("trend_gbm", 0.80),
        ("jev", 0.30),
    ]


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
        p_trend_gbm=0.62,
        trend_gbm_trade=True,
        allow_exit=allow_exit,
        allow_entry=allow_entry,
    )

    assert bool(exit_candidates) is allow_exit, elapsed
    assert bool(entry_candidates) is allow_entry, elapsed
    if allow_exit:
        assert "trend_gbm" in [candidate.model for candidate in exit_candidates]
    if allow_entry:
        assert "trend_gbm" in [candidate.model for candidate in entry_candidates]
        assert "gbm" in [candidate.model for candidate in entry_candidates]
        assert "jev" in [candidate.model for candidate in entry_candidates]
    if allow_exit and not allow_entry:
        assert [candidate.model for candidate in exit_candidates] == [
            "gbm",
            "trend_gbm",
            "jev",
            "jev_mkt",
        ]


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


def test_database_check_validates_and_closes_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    class FakeStore:
        def initialize(self) -> None:
            calls.append("initialize")

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(cli, "create_store", lambda *_args, **_kwargs: FakeStore())
    settings = Settings(
        _env_file=None,
        db_url="postgresql://postgres:secret@localhost:5432/postgres",
    )

    cli.check_database(settings)

    assert calls == ["initialize", "close"]
    assert "[OK] database: PostgreSQL public schema" in capsys.readouterr().out
