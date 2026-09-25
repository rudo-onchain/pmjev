"""Application settings loaded from environment variables and ``.env``."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Environment variables use the field names in uppercase."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    mode: Literal["paper", "shadow", "live"] = "paper"
    assets: str | None = None
    assets_file: Path = Path("assets.yaml")
    checkpoints: str | None = None
    entry_checkpoints: str | None = None
    exit_checkpoints: str | None = None
    jev_enabled: bool = True
    jev_market_variant: bool = True
    gbm_trade: bool = True
    jev_timeout_s: float = Field(default=1.5, gt=0)
    typesafe_api_key: str | None = None
    edge: float | None = Field(default=None, ge=0, le=1)
    fee_peak: float = Field(default=0.018, ge=0, le=1)
    db_url: str = "sqlite:///pmjev.sqlite"
    poly_private_key: str | None = None
    max_notional_usd: float | None = Field(default=None, gt=0)
    stake_usd: float | None = Field(default=None, gt=0)
    daily_loss_limit_usd: float = Field(default=25.0, gt=0)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_message_thread_id: int | None = None
    gamma_url: str = "https://gamma-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"
    chainlink_ws_url: str = "wss://ws-live-data.polymarket.com"
    chainlink_topic: str = "crypto_prices_twap_sixty"
    binance_url: str = "https://api.binance.com"
    binance_ws_url: str = "wss://stream.binance.com:9443/ws"
    hyperliquid_url: str = "https://api.hyperliquid.xyz"
    hyperliquid_ws_url: str = "wss://api.hyperliquid.xyz/ws"
    http_timeout_s: float = Field(default=5.0, gt=0)

    @field_validator(
        "assets",
        "checkpoints",
        "entry_checkpoints",
        "exit_checkpoints",
        "typesafe_api_key",
        "edge",
        "poly_private_key",
        "max_notional_usd",
        "stake_usd",
        "telegram_bot_token",
        "telegram_chat_id",
        "telegram_message_thread_id",
        mode="before",
    )
    @classmethod
    def blank_string_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def reject_unimplemented_execution_modes(self) -> Settings:
        # Phase 0/1 intentionally permits constructing these settings so the executor's
        # explicit NotImplementedError remains the single execution-mode boundary.
        if bool(self.telegram_bot_token) != bool(self.telegram_chat_id):
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be configured together"
            )
        return self

    @property
    def enabled_asset_names(self) -> set[str] | None:
        if self.assets is None:
            return None
        names = {name.strip().lower() for name in self.assets.split(",") if name.strip()}
        if not names:
            return None
        return names

    @property
    def checkpoint_override(self) -> tuple[int, ...] | None:
        return self._parse_checkpoints(self.checkpoints, "CHECKPOINTS")

    @property
    def entry_checkpoint_override(self) -> tuple[int, ...] | None:
        return self._parse_checkpoints(self.entry_checkpoints, "ENTRY_CHECKPOINTS")

    @property
    def exit_checkpoint_override(self) -> tuple[int, ...] | None:
        return self._parse_checkpoints(self.exit_checkpoints, "EXIT_CHECKPOINTS")

    @staticmethod
    def _parse_checkpoints(value: str | None, setting: str) -> tuple[int, ...] | None:
        if value is None:
            return None
        try:
            values = tuple(int(item.strip()) for item in value.split(","))
        except ValueError as exc:
            raise ValueError(f"{setting} must be a comma-separated list of integers") from exc
        if not values or any(value <= 0 for value in values):
            raise ValueError(f"{setting} must contain positive integers")
        if tuple(sorted(set(values))) != values:
            raise ValueError(f"{setting} must be unique and strictly increasing")
        return values
