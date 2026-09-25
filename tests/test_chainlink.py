from __future__ import annotations

from pathlib import Path

import pytest

from pmjev.feeds.chainlink import (
    build_subscription,
    parse_chainlink_message,
    select_price_to_beat,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_subscription_uses_verified_compact_string_filters() -> None:
    payload = build_subscription(["btc/usd", "hype/usd"], "crypto_prices_twap_sixty")
    assert payload == {
        "action": "subscribe",
        "subscriptions": [
            {
                "topic": "crypto_prices_twap_sixty",
                "type": "update",
                "filters": '{"symbol":"btc/usd"}',
            },
            {
                "topic": "crypto_prices_twap_sixty",
                "type": "update",
                "filters": '{"symbol":"hype/usd"}',
            },
        ],
    }


def test_parse_twap_subscription_snapshot() -> None:
    raw = (FIXTURES / "chainlink_twap_snapshot.json").read_text(encoding="utf-8")
    ticks = parse_chainlink_message(raw)
    assert len(ticks) == 2
    assert ticks[0].symbol == "btc/usd"
    assert ticks[0].timestamp == pytest.approx(1_790_231_122)
    assert ticks[0].price == pytest.approx(84_111.17591825358)


def test_select_price_to_beat_uses_exact_boundary_tick() -> None:
    raw = (FIXTURES / "chainlink_twap_snapshot.json").read_text(encoding="utf-8")
    tick = select_price_to_beat(parse_chainlink_message(raw), 1_790_231_123)
    assert tick is not None
    assert tick.timestamp == 1_790_231_123


def test_empty_and_pong_frames_are_ignored() -> None:
    assert parse_chainlink_message("") == []
    assert parse_chainlink_message("PONG") == []
