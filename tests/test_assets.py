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


def test_blank_max_notional_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_NOTIONAL_USD", "")
    assert Settings(_env_file=None).max_notional_usd is None
