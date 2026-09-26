from __future__ import annotations

from pmjev.features import build_10s_klines
from pmjev.feeds.base import Trade


def test_build_10s_klines_fills_empty_bins_with_previous_close() -> None:
    trades = [
        Trade(timestamp=101.0, price=100.0, quantity=2.0, is_buyer_maker=False),
        Trade(timestamp=108.0, price=102.0, quantity=1.0, is_buyer_maker=True),
        Trade(timestamp=123.0, price=99.0, quantity=3.0, is_buyer_maker=False),
    ]

    klines = build_10s_klines(
        trades,
        start=100.0,
        end=130.0,
        seed_price=98.0,
    )

    assert len(klines) == 3
    assert klines[0].open == 100.0
    assert klines[0].high == 102.0
    assert klines[0].low == 100.0
    assert klines[0].close == 102.0
    assert klines[0].volume == 3.0
    assert klines[0].buy_volume_ratio == 2 / 3
    assert klines[1].open == 102.0
    assert klines[1].close == 102.0
    assert klines[1].volume == 0.0
    assert klines[1].buy_volume_ratio == 0.5
    assert klines[2].open == 99.0
    assert klines[2].close == 99.0
    assert klines[2].volume == 3.0
    assert klines[2].buy_volume_ratio == 1.0


def test_build_10s_klines_returns_exactly_30_bins_for_five_minutes() -> None:
    klines = build_10s_klines([], start=0.0, end=300.0, seed_price=100.0)

    assert len(klines) == 30
    assert klines[0].start == 0.0
    assert klines[-1].end == 300.0
    assert all(kline.close == 100.0 for kline in klines)
