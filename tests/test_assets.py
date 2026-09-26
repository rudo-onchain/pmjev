from __future__ import annotations

from pathlib import Path

import pytest

from pmjev.assets import build_slug, load_assets
from pmjev.config import Settings


def write_assets(path: Path) -> None:
    path.write_text(
        """
defaults:
  window_seconds: 300
  checkpoints: [60, 150]
  edge: 0.03
  stake_usd: 5
  jev: {enabled: true, market_variant: true}
assets:
  btc:
    enabled: true
    slug_prefix: btc-updown-5m
    chainlink_symbol: btc/usd
    feature_source: {type: binance, symbol: BTCUSDT}
  hype:
    enabled: false
    slug_prefix: hype-updown-5m
    chainlink_symbol: hype/usd
    feature_source: {type: hyperliquid, coin: HYPE}
    edge: 0.05
""".strip(),
        encoding="utf-8",
    )


def test_load_assets_merges_defaults(tmp_path: Path) -> None:
    path = tmp_path / "assets.yaml"
    write_assets(path)
    assets = load_assets(path)
    assert [asset.name for asset in assets] == ["btc"]
    assert assets[0].checkpoints == (60, 150)
    assert assets[0].edge == pytest.approx(0.03)


def test_assets_override_can_enable_disabled_asset(tmp_path: Path) -> None:
    path = tmp_path / "assets.yaml"
    write_assets(path)
    assets = load_assets(path, enabled_names={"hype"})
    assert [asset.name for asset in assets] == ["hype"]
    assert assets[0].edge == pytest.approx(0.05)


def test_unknown_asset_override_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "assets.yaml"
    write_assets(path)
    with pytest.raises(ValueError, match="unknown assets"):
        load_assets(path, enabled_names={"doge"})


def test_invalid_checkpoint_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "assets.yaml"
    write_assets(path)
    with pytest.raises(ValueError, match="before window_seconds"):
        load_assets(path, checkpoint_override=(300,))


def test_slug_building(tmp_path: Path) -> None:
    path = tmp_path / "assets.yaml"
    write_assets(path)
    asset = load_assets(path)[0]
    assert build_slug(asset, 1_790_123_400) == "btc-updown-5m-1790123400"


def test_assets_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSETS", "btc,hype")
    assert Settings(_env_file=None).enabled_asset_names == {"btc", "hype"}


def test_trend_gbm_trade_parses_independently_of_gbm_trade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GBM_TRADE", "true")
    monkeypatch.setenv("TREND_GBM_TRADE", "false")
    settings = Settings(_env_file=None)

    assert settings.gbm_trade is True
    assert settings.trend_gbm_trade is False


def test_entry_safety_settings_parse_and_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_MODEL_MARKET_GAP", "0.25")

    settings = Settings(_env_file=None)

    assert settings.jev_enabled is True
    assert settings.jev_trade is False
    assert settings.max_model_market_gap == pytest.approx(0.25)
    with pytest.raises(ValueError, match="less than or equal to 1"):
        Settings(_env_file=None, max_model_market_gap=1.01)


def test_checkpoint_budget_covers_io_predictor_and_database_grace() -> None:
    derived = Settings(
        _env_file=None,
        http_timeout_s=5.0,
        jev_enabled=True,
        jev_timeout_s=1.5,
        deepseek_enabled=True,
        deepseek_timeout_s=2.5,
        openrouter_api_key="test",
    )
    overridden = Settings(_env_file=None, checkpoint_budget_s=12.0)

    assert derived.effective_checkpoint_budget_s == pytest.approx(8.5)
    assert overridden.effective_checkpoint_budget_s == pytest.approx(12.0)


def test_deepseek_is_restricted_to_enabled_paper_mode() -> None:
    with pytest.raises(ValueError, match="restricted to MODE=paper"):
        Settings(_env_file=None, mode="shadow", deepseek_enabled=True)

    with pytest.raises(ValueError, match="requires DEEPSEEK_ENABLED"):
        Settings(_env_file=None, deepseek_trade=True)

    settings = Settings(
        _env_file=None,
        mode="paper",
        deepseek_enabled=True,
        deepseek_trade=True,
    )
    assert settings.deepseek_model == "deepseek/deepseek-v4.1-flash"


def test_action_checkpoint_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTRY_CHECKPOINTS", "150,240")
    monkeypatch.setenv("EXIT_CHECKPOINTS", "240,280")
    settings = Settings(_env_file=None)

    assert settings.entry_checkpoint_override == (150, 240)
    assert settings.exit_checkpoint_override == (240, 280)


def test_action_checkpoints_must_be_unique_and_increasing() -> None:
    settings = Settings(_env_file=None, entry_checkpoints="240,150")
    with pytest.raises(ValueError, match="unique and strictly increasing"):
        _ = settings.entry_checkpoint_override


def test_blank_max_notional_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_NOTIONAL_USD", "")
    assert Settings(_env_file=None).max_notional_usd is None


def test_database_pool_maximum_cannot_be_smaller_than_minimum() -> None:
    with pytest.raises(ValueError, match="DB_POOL_MAX_SIZE must be >= DB_POOL_MIN_SIZE"):
        Settings(_env_file=None, db_pool_min_size=5, db_pool_max_size=4)


def test_telegram_credentials_must_be_configured_together() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"):
        Settings(_env_file=None, telegram_bot_token="token")

    settings = Settings(
        _env_file=None,
        telegram_bot_token="token",
        telegram_chat_id="12345",
    )
    assert settings.telegram_bot_token == "token"
    assert settings.telegram_chat_id == "12345"


def test_blank_telegram_thread_id_is_unset() -> None:
    settings = Settings(_env_file=None, telegram_message_thread_id="")
    assert settings.telegram_message_thread_id is None


def test_live_mode_requires_explicit_arming_and_credentials() -> None:
    with pytest.raises(ValueError, match="MODE=live is not armed"):
        Settings(_env_file=None, mode="live")


def test_auto_reference_feed_uses_polybolt_when_credentials_exist() -> None:
    settings = Settings(
        _env_file=None,
        poly_api_key="key",
        poly_api_secret="secret",
        poly_api_passphrase="pass",
    )
    assert settings.use_polybolt is True
