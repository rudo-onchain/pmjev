from __future__ import annotations

import json

import httpx
import pytest

from pmjev.predictors.deepseek import DeepSeekPredictor


@pytest.mark.asyncio
async def test_deepseek_returns_structured_probability_and_provider() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "provider": "DeepSeek",
                "choices": [{"message": {"content": '{"p_up":0.63}'}}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        predictor = DeepSeekPredictor(
            client,
            api_key="secret",
            model="deepseek/deepseek-v4.1-flash",
            url="https://openrouter.test/api/v1/chat/completions",
            timeout_s=2.5,
        )
        result = await predictor.predict({"spot": 101, "price_to_beat": 100})

    assert result.probability == pytest.approx(0.63)
    assert result.provider == "DeepSeek"
    assert result.error is None
    assert captured["model"] == "deepseek/deepseek-v4.1-flash"
    assert captured["temperature"] == 0
    assert captured["max_tokens"] == 32
    assert captured["reasoning"] == {"enabled": False}
    assert captured["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "five_minute_market_prediction",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "p_up": {"type": "number", "minimum": 0, "maximum": 1}
                },
                "required": ["p_up"],
                "additionalProperties": False,
            },
        },
    }


@pytest.mark.asyncio
async def test_deepseek_records_invalid_response_without_raising() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"p_up":1.2}'}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        predictor = DeepSeekPredictor(
            client,
            api_key="secret",
            model="deepseek/deepseek-v4.1-flash",
            url="https://openrouter.test/api/v1/chat/completions",
            timeout_s=2.5,
        )
        result = await predictor.predict({})

    assert result.probability is None
    assert result.error is not None and "out-of-range" in result.error


@pytest.mark.asyncio
async def test_deepseek_reports_token_limit_instead_of_json_decode_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "unfinished reasoning"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        predictor = DeepSeekPredictor(
            client,
            api_key="secret",
            model="deepseek/deepseek-v4.1-flash",
            url="https://openrouter.test/api/v1/chat/completions",
            timeout_s=2.5,
        )
        result = await predictor.predict({})

    assert result.probability is None
    assert result.error == "ValueError: DeepSeek response truncated (finish_reason=length)"
