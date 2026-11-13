"""LiteLLMClient request mapping, with litellm.acompletion patched (no model needed)."""

from types import SimpleNamespace
from typing import Any

import litellm
import pytest

from housing_netherlands.adapters import llm_litellm
from housing_netherlands.adapters.llm_litellm import LiteLLMClient
from housing_netherlands.config import Settings
from housing_netherlands.core import ports
from housing_netherlands.core.errors import LLMUnavailableError
from housing_netherlands.core.models import ListingSummary, LLMMessage, LLMParams
from housing_netherlands.wiring import build_llm_client, extract_llm_params


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> Any:
        calls.update(kwargs)
        message = SimpleNamespace(content=calls.pop("_reply", '{"ok": true}'))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(llm_litellm.litellm, "acompletion", fake_acompletion)
    return calls


MESSAGES = [LLMMessage(role="system", content="s"), LLMMessage(role="user", content="u")]


def test_implements_port() -> None:
    assert isinstance(LiteLLMClient(ollama_api_base=None, timeout_s=1), ports.LLMClient)


async def test_maps_request_and_response(captured: dict[str, Any]) -> None:
    client = LiteLLMClient(ollama_api_base="http://ollama:11434", timeout_s=42)
    schema = ListingSummary.model_json_schema()
    params = LLMParams(model="ollama_chat/qwen3.5:4b", reasoning_effort="none")
    response = await client.complete(MESSAGES, params=params, json_schema=schema)

    assert response.text == '{"ok": true}'
    assert response.model == "ollama_chat/qwen3.5:4b"
    assert captured["model"] == "ollama_chat/qwen3.5:4b"
    assert captured["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    assert (captured["api_base"], captured["timeout"]) == ("http://ollama:11434", 42)
    assert captured["reasoning_effort"] == "none"
    assert captured["drop_params"] is True
    fmt = captured["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"] == {"name": "ListingSummary", "schema": schema}


async def test_plain_text_call_sends_no_response_format(captured: dict[str, Any]) -> None:
    client = LiteLLMClient(ollama_api_base=None, timeout_s=1)
    await client.complete(MESSAGES, params=LLMParams(model="m"))
    assert "response_format" not in captured
    assert "reasoning_effort" not in captured


async def test_none_content_becomes_empty_string(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def none_content(**kwargs: Any) -> Any:
        message = SimpleNamespace(content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(llm_litellm.litellm, "acompletion", none_content)
    client = LiteLLMClient(ollama_api_base=None, timeout_s=1)
    response = await client.complete(MESSAGES, params=LLMParams(model="m"))
    assert response.text == ""


@pytest.mark.parametrize(
    "model", ["anthropic/claude-haiku-5-5", "gpt-5-mini", "bedrock/anthropic.claude-haiku"]
)
async def test_hosted_models_never_get_the_ollama_url(captured: dict[str, Any], model: str) -> None:
    client = LiteLLMClient(ollama_api_base="http://localhost:11434", timeout_s=1)
    await client.complete(MESSAGES, params=LLMParams(model=model))
    assert "api_base" not in captured  # provider's own endpoint


@pytest.mark.parametrize("model", ["ollama_chat/qwen3.5:4b", "ollama/qwen3.5:4b"])
async def test_ollama_models_get_the_ollama_url(captured: dict[str, Any], model: str) -> None:
    client = LiteLLMClient(ollama_api_base="http://ollama:11434", timeout_s=1)
    await client.complete(MESSAGES, params=LLMParams(model=model))
    assert captured["api_base"] == "http://ollama:11434"


def test_wiring_passes_llm_settings() -> None:
    settings = Settings(
        llm_model_extract="anthropic/claude-haiku-5-5",
        ollama_api_base="http://x:1",
        llm_timeout_s=7,
        llm_reasoning_effort="low",
    )  # type: ignore[call-arg]
    client = build_llm_client(settings)
    assert (client._ollama_api_base, client._timeout_s) == ("http://x:1", 7)
    assert extract_llm_params(settings) == LLMParams(
        model="anthropic/claude-haiku-5-5", reasoning_effort="low"
    )


# --- error mapping: temporary vs permanent -----------------------------------------------


def _litellm_error(cls: type[Exception]) -> Exception:
    return cls(message="boom", llm_provider="ollama", model="qwen3.5:4b")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "error_cls",
    [
        litellm.exceptions.APIConnectionError,
        litellm.exceptions.Timeout,
        litellm.exceptions.RateLimitError,
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.InternalServerError,
        litellm.exceptions.BadGatewayError,
    ],
)
async def test_temporary_llm_errors_become_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch, error_cls: type[Exception]
) -> None:
    async def failing(**kwargs: Any) -> Any:
        raise _litellm_error(error_cls)

    monkeypatch.setattr(llm_litellm.litellm, "acompletion", failing)
    client = LiteLLMClient(ollama_api_base=None, timeout_s=1)
    with pytest.raises(LLMUnavailableError) as exc_info:
        await client.complete(MESSAGES, params=LLMParams(model="ollama_chat/qwen3.5:4b"))
    assert exc_info.value.retryable
    assert isinstance(exc_info.value.__cause__, error_cls)


@pytest.mark.parametrize(
    "error_cls",
    [
        litellm.exceptions.AuthenticationError,
        litellm.exceptions.BadRequestError,
        litellm.exceptions.NotFoundError,  # e.g. model not pulled
    ],
)
async def test_permanent_llm_errors_are_not_wrapped(
    monkeypatch: pytest.MonkeyPatch, error_cls: type[Exception]
) -> None:
    async def failing(**kwargs: Any) -> Any:
        raise _litellm_error(error_cls)

    monkeypatch.setattr(llm_litellm.litellm, "acompletion", failing)
    client = LiteLLMClient(ollama_api_base=None, timeout_s=1)
    with pytest.raises(error_cls):
        await client.complete(MESSAGES, params=LLMParams(model="ollama_chat/qwen3.5:4b"))


async def test_unreachable_ollama_raises_llm_unavailable() -> None:
    # Real litellm call to a closed port: the same error as "Ollama is restarting".
    client = LiteLLMClient(ollama_api_base="http://127.0.0.1:9", timeout_s=5)
    with pytest.raises(LLMUnavailableError, match="APIConnectionError"):
        await client.complete(MESSAGES, params=LLMParams(model="ollama_chat/qwen3.5:4b"))
