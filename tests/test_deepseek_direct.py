from __future__ import annotations

import json

import httpx
import pytest

from pmjev.features import Kline10s
from pmjev.predictors.deepseek_direct import (
    DeepSeekDirectPredictor,
    DirectMarketContext,
)


@pytest.mark.asyncio
async def test_direct_predictor_sends_klines_market_and_fees() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "provider": "DeepSeek",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"action":"buy_down","p_up":0.58}'
                        },
                    }
                ],
            },
        )

    klines = tuple(
        Kline10s(
            start=float(index * 10),
            end=float((index + 1) * 10),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=2.0,
            buy_volume_ratio=0.75,
        )
        for index in range(30)
    )
    context = DirectMarketContext(
        chainlink_spot=101.0,
        feature_spot=100.5,
        price_to_beat=100.0,
        seconds_remaining=150,
        up_bid=0.69,
        up_ask=0.71,
        down_bid=0.27,
        down_ask=0.29,
        fee_rate=0.07,
        fee_exponent=1,
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        predictor = DeepSeekDirectPredictor(
            client,
            api_key="secret",
            model="deepseek/deepseek-v4.1-flash",
            url="https://openrouter.test/api/v1/chat/completions",
            timeout_s=2.5,
        )
        result = await predictor.predict(klines, context)

    assert result.action == "buy_down"
    assert result.probability_up == pytest.approx(0.58)
    assert result.provider == "DeepSeek"
    messages = captured["messages"]
    assert isinstance(messages, list)
    prompt = json.loads(messages[1]["content"])
    assert len(prompt["klines_10s"]) == 30
    assert prompt["market"]["down_ask"] == pytest.approx(0.29)
    assert prompt["market"]["up_fee_per_share"] > 0
    assert prompt["market"]["down_fee_per_share"] > 0
    assert captured["reasoning"] == {"enabled": False}


@pytest.mark.asyncio
async def test_direct_predictor_rejects_unknown_action() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"action":"hold","p_up":0.5}'}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        predictor = DeepSeekDirectPredictor(
            client,
            api_key="secret",
            model="deepseek/deepseek-v4.1-flash",
            url="https://openrouter.test/api/v1/chat/completions",
            timeout_s=2.5,
        )
        result = await predictor.predict(
            (),
            DirectMarketContext(
                chainlink_spot=100.0,
                feature_spot=100.0,
                price_to_beat=100.0,
                seconds_remaining=60,
                up_bid=None,
                up_ask=None,
                down_bid=None,
                down_ask=None,
                fee_rate=0.07,
                fee_exponent=1,
            ),
        )

    assert result.action is None
    assert result.error is not None and "unknown action" in result.error
