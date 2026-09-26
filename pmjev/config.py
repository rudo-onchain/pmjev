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
    jev_trade: bool = False
    jev_market_variant: bool = True
    gbm_trade: bool = True
    trend_gbm_trade: bool = True
    jev_timeout_s: float = Field(default=1.5, gt=0)
    typesafe_api_key: str | None = None
    deepseek_enabled: bool = False
    deepseek_trade: bool = False
    deepseek_timeout_s: float = Field(default=2.5, gt=0)
    deepseek_model: str = "deepseek/deepseek-v4.1-flash"
    openrouter_api_key: str | None = None
    openrouter_url: str = "https://openrouter.ai/api/v1/chat/completions"
    edge: float | None = Field(default=None, ge=0, le=1)
    max_model_market_gap: float = Field(default=0.25, ge=0, le=1)
    fee_peak: float = Field(default=0.018, ge=0, le=1)
    db_url: str = "sqlite:///pmjev.sqlite"
    db_pool_min_size: int = Field(default=1, ge=0)
    db_pool_max_size: int = Field(default=4, gt=0)
    db_connect_timeout_s: float = Field(default=5.0, gt=0)
    checkpoint_budget_s: float | None = Field(default=None, gt=0)
    dashboard_starting_balance_usd: float = Field(default=100.0, gt=0)
    reference_feed: Literal["auto", "legacy", "polybolt"] = "auto"
    polybolt_ws_url: str = "wss://ws-live-v2.polymarket.com/ws"
    poly_api_key: str | None = None
    poly_api_secret: str | None = None
    poly_api_passphrase: str | None = None
    poly_private_key: str | None = None
    poly_wallet: str | None = None
    live_trading_enabled: bool = False
    max_notional_usd: float | None = Field(default=None, gt=0)
    live_max_trade_usd: float = Field(default=10.0, gt=0)
    live_min_shares: float = Field(default=5.0, gt=0)
    stake_usd: float | None = Field(default=None, gt=0)
    daily_loss_limit_usd: float = Field(default=25.0, gt=0)
    consecutive_loss_limit: int = Field(default=8, gt=0)
    loss_pause_seconds: int = Field(default=3600, gt=0)
    max_drawdown_usd: float = Field(default=100.0, gt=0)
    risk_reset_at: float = Field(default=0.0, ge=0)
    stop_file: Path = Path("STOP")
    reference_stale_seconds: float = Field(default=10.0, gt=0)
    jev_error_window_seconds: int = Field(default=1800, gt=0)
    jev_error_rate_limit: float = Field(default=0.20, gt=0, le=1)
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
        "openrouter_api_key",
        "edge",
        "poly_api_key",
        "poly_api_secret",
        "poly_api_passphrase",
        "poly_private_key",
        "poly_wallet",
        "max_notional_usd",
        "stake_usd",
        "checkpoint_budget_s",
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
    def validate_credentials_and_live_gate(self) -> Settings:
        if self.db_pool_max_size < self.db_pool_min_size:
            raise ValueError("DB_POOL_MAX_SIZE must be >= DB_POOL_MIN_SIZE")
        if bool(self.telegram_bot_token) != bool(self.telegram_chat_id):
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be configured together"
            )
        if self.deepseek_enabled and self.mode != "paper":
            raise ValueError("DeepSeek is restricted to MODE=paper")
        if self.deepseek_trade and not self.deepseek_enabled:
            raise ValueError("DEEPSEEK_TRADE=true requires DEEPSEEK_ENABLED=true")
        credentials = (
            self.poly_api_key,
            self.poly_api_secret,
            self.poly_api_passphrase,
        )
        if any(credentials) and not all(credentials):
            raise ValueError(
                "POLY_API_KEY, POLY_API_SECRET, and POLY_API_PASSPHRASE "
                "must be configured together"
            )
        if self.reference_feed == "polybolt" and not all(credentials):
            raise ValueError("REFERENCE_FEED=polybolt requires all POLY_API_* credentials")
        if self.mode == "live":
            missing: list[str] = []
            if not self.live_trading_enabled:
                missing.append("LIVE_TRADING_ENABLED=true")
            if self.max_notional_usd is None:
                missing.append("MAX_NOTIONAL_USD")
            if not self.poly_private_key:
                missing.append("POLY_PRIVATE_KEY")
            if not self.poly_wallet:
                missing.append("POLY_WALLET")
            if not all(credentials):
                missing.append("POLY_API_KEY/SECRET/PASSPHRASE")
            if missing:
                raise ValueError("MODE=live is not armed; missing " + ", ".join(missing))
            if self.max_notional_usd is not None and (
                self.live_max_trade_usd > self.max_notional_usd
            ):
                raise ValueError("LIVE_MAX_TRADE_USD cannot exceed MAX_NOTIONAL_USD")
        return self

    @property
    def use_polybolt(self) -> bool:
        if self.reference_feed == "polybolt":
            return True
        if self.reference_feed == "legacy":
            return False
        return bool(self.poly_api_key and self.poly_api_secret and self.poly_api_passphrase)

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

    @property
    def effective_checkpoint_budget_s(self) -> float:
        if self.checkpoint_budget_s is not None:
            return self.checkpoint_budget_s
        predictor_timeouts = [0.0]
        if self.jev_enabled:
            predictor_timeouts.append(self.jev_timeout_s)
        if self.deepseek_enabled:
            predictor_timeouts.append(self.deepseek_timeout_s)
        return self.http_timeout_s + max(predictor_timeouts) + 1.0

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
