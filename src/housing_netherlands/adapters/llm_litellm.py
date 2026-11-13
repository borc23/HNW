"""`LLMClient` on LiteLLM: one interface for Ollama now and hosted models / Bedrock later.

The model is chosen per call (e.g. LLM_MODEL_EXTRACT), so switching between a local Ollama
model and a hosted one is a config change: the Ollama base URL is only sent to ollama/* models,
hosted providers always use their own endpoint.
"""

import os
from typing import Any

# Must be set before importing litellm: otherwise every import fetches the model cost map over
# the network (5 s timeout; slow or hanging offline / behind restricted egress). The packaged
# map for the pinned version is used instead. setdefault keeps an explicit env override.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from litellm import ModelResponse

from housing_netherlands.core.errors import LLMUnavailableError
from housing_netherlands.core.models import LLMMessage, LLMParams, LLMResponse

litellm.suppress_debug_info = True

OLLAMA_PREFIXES = ("ollama/", "ollama_chat/")

# Temporary: the request was fine but the model wasn't reachable or was overloaded.
# APIConnectionError covers Ollama being down ("connection refused"). litellm.Timeout must be
# listed too: it derives from openai's APIConnectionError, not litellm's.
# Anything else (auth, bad request, model not found, context too long) won't fix itself.
_TRANSIENT = (
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.Timeout,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.BadGatewayError,
)


class LiteLLMClient:
    def __init__(
        self,
        *,
        ollama_api_base: str | None,
        timeout_s: float,
    ) -> None:
        self._ollama_api_base = ollama_api_base
        self._timeout_s = timeout_s

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        params: LLMParams,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {}
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": json_schema.get("title", "output"), "schema": json_schema},
            }
        if params.model.startswith(OLLAMA_PREFIXES):
            kwargs["api_base"] = self._ollama_api_base
        if params.reasoning_effort:
            # "none" turns off "thinking" on reasoning models (qwen3.5 on CPU: ~25 s vs >180 s).
            kwargs["reasoning_effort"] = params.reasoning_effort
        try:
            response = await self._acompletion(messages, params, kwargs)
        except _TRANSIENT as exc:
            raise LLMUnavailableError(params.model, f"{type(exc).__name__}: {exc}") from exc
        return LLMResponse(text=response.choices[0].message.content or "", model=params.model)

    async def _acompletion(
        self, messages: list[LLMMessage], params: LLMParams, kwargs: dict[str, Any]
    ) -> ModelResponse:
        # Without stream=True, acompletion returns a ModelResponse (never a stream wrapper).
        return await litellm.acompletion(  # type: ignore[return-value]
            model=params.model,
            messages=[m.model_dump() for m in messages],
            timeout=self._timeout_s,
            drop_params=True,  # skip params a provider doesn't support instead of failing
            **kwargs,
        )
