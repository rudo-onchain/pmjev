"""Validated, data-driven asset configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class JevConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    market_variant: bool = True


class BinanceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["binance"]
    symbol: str = Field(min_length=1)


class HyperliquidSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["hyperliquid"]
    coin: str = Field(min_length=1)


FeatureSourceConfig = Annotated[
    BinanceSource | HyperliquidSource,
    Field(discriminator="type"),
]


class AssetDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_seconds: int = Field(default=300, gt=0)
    checkpoints: tuple[int, ...] = (60, 150, 240, 280)
    edge: float = Field(default=0.03, ge=0, le=1)
    stake_usd: float = Field(default=5.0, gt=0)
    jev: JevConfig = Field(default_factory=JevConfig)

    @model_validator(mode="after")
    def checkpoints_fit_window(self) -> AssetDefaults:
        if not self.checkpoints:
            raise ValueError("checkpoints cannot be empty")
        if tuple(sorted(set(self.checkpoints))) != self.checkpoints:
            raise ValueError("checkpoints must be unique and strictly increasing")
        if self.checkpoints[-1] >= self.window_seconds:
            raise ValueError("all checkpoints must be before window_seconds")
        return self


class AssetOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    slug_prefix: str = Field(min_length=1)
    chainlink_symbol: str = Field(min_length=1)
    feature_source: FeatureSourceConfig
    window_seconds: int | None = Field(default=None, gt=0)
    checkpoints: tuple[int, ...] | None = None
    edge: float | None = Field(default=None, ge=0, le=1)
    stake_usd: float | None = Field(default=None, gt=0)
    jev: JevConfig | None = None


class AssetsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: AssetDefaults
    assets: dict[str, AssetOverride]

    @model_validator(mode="after")
    def contains_assets(self) -> AssetsFile:
        if not self.assets:
            raise ValueError("assets cannot be empty")
        return self


class AssetConfig(BaseModel):
    """Fully resolved configuration for one enabled asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    slug_prefix: str
    chainlink_symbol: str
    feature_source: FeatureSourceConfig
    window_seconds: int
    checkpoints: tuple[int, ...]
    edge: float
    stake_usd: float
    jev: JevConfig

    @model_validator(mode="after")
    def checkpoints_fit_window(self) -> AssetConfig:
        if not self.checkpoints:
            raise ValueError("checkpoints cannot be empty")
        if tuple(sorted(set(self.checkpoints))) != self.checkpoints:
            raise ValueError("checkpoints must be unique and strictly increasing")
        if self.checkpoints[-1] >= self.window_seconds:
            raise ValueError("all checkpoints must be before window_seconds")
        return self


def load_assets(
    path: Path | str,
    enabled_names: set[str] | None = None,
    checkpoint_override: tuple[int, ...] | None = None,
    edge_override: float | None = None,
    stake_override: float | None = None,
) -> list[AssetConfig]:
    """Load, validate, merge defaults, and filter ``assets.yaml``.

    Raises a useful ``ValueError`` immediately for malformed YAML, unknown ASSETS names,
    or invalid merged configuration.
    """

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        parsed = AssetsFile.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"Invalid assets file {config_path}: {exc}") from exc

    known = {name.lower() for name in parsed.assets}
    if enabled_names is not None:
        unknown = enabled_names - known
        if unknown:
            raise ValueError(f"ASSETS contains unknown assets: {', '.join(sorted(unknown))}")

    result: list[AssetConfig] = []
    defaults = parsed.defaults
    for raw_name, override in parsed.assets.items():
        name = raw_name.lower()
        enabled = override.enabled if enabled_names is None else name in enabled_names
        if not enabled:
            continue
        result.append(
            AssetConfig(
                name=name,
                slug_prefix=override.slug_prefix,
                chainlink_symbol=override.chainlink_symbol,
                feature_source=override.feature_source,
                window_seconds=override.window_seconds or defaults.window_seconds,
                checkpoints=checkpoint_override or override.checkpoints or defaults.checkpoints,
                edge=edge_override
                if edge_override is not None
                else (override.edge if override.edge is not None else defaults.edge),
                stake_usd=stake_override
                if stake_override is not None
                else (override.stake_usd if override.stake_usd is not None else defaults.stake_usd),
                jev=override.jev or defaults.jev,
            )
        )
    if not result:
        raise ValueError("No assets are enabled")
    return result


def build_slug(asset: AssetConfig, window_start: int) -> str:
    """Build the deterministic Gamma market slug for one window."""

    return f"{asset.slug_prefix}-{window_start}"
