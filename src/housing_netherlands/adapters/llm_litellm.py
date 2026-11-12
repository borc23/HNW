"""`LLMClient` on LiteLLM: one interface for Ollama now and hosted models / Bedrock later.

The model is chosen per call (e.g. LLM_MODEL_EXTRACT), so switching between a local Ollama
model and a hosted one is a config change: the Ollama base URL is only sent to ollama/* models,
hosted providers always use their own endpoint.
"""

from typing import Any

import litellm
from litellm import ModelResponse

from housing_netherlands.core.models import LLMMessage, LLMParams, LLMResponse

litellm.suppress_debug_info = True

OLLAMA_PREFIXES = ("ollama/", "ollama_chat/")


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
        # Without stream=True, acompletion returns a ModelResponse (never a stream wrapper).
        response: ModelResponse = await litellm.acompletion(  # type: ignore[assignment]
            model=params.model,
            messages=[m.model_dump() for m in messages],
            timeout=self._timeout_s,
            drop_params=True,  # skip params a provider doesn't support instead of failing
            **kwargs,
        )
        return LLMResponse(text=response.choices[0].message.content or "", model=params.model)
