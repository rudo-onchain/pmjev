from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmjev.market.gamma import parse_market, parse_outcome

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "expected"),
    [("gamma_up.json", 1), ("gamma_down.json", 0), ("gamma_open.json", None)],
)
def test_parse_outcome(name: str, expected: int | None) -> None:
    assert parse_outcome(fixture(name)) == expected


def test_parse_market_maps_tokens_by_outcome_name() -> None:
    market = parse_market(fixture("gamma_up.json"), "btc-updown-5m-1000")
    assert market.up_token == "up-token"
    assert market.down_token == "down-token"
    assert market.fee_rate == pytest.approx(0.07)
    assert market.fee_exponent == 1
    assert market.twap_lookback_seconds == 60


def test_parse_outcome_rejects_non_binary_settlement() -> None:
    event = fixture("gamma_up.json")
    event["markets"][0]["outcomePrices"] = '["0.5", "0.5"]'
    with pytest.raises(ValueError, match="not settled"):
        parse_outcome(event)
