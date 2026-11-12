"""`LLMClient` on LiteLLM: one interface for Ollama now and hosted models / Bedrock later.

The model is chosen per call (e.g. LLM_MODEL_EXTRACT), so switching between a local Ollama
model and a hosted one is a config change.
"""

from typing import Any

import litellm
from litellm import ModelResponse

from housing_netherlands.core.models import LLMMessage, LLMResponse

litellm.suppress_debug_info = True


class LiteLLMClient:
    def __init__(
        self,
        *,
        api_base: str | None,
        timeout_s: float,
        reasoning_effort: str | None = None,
    ) -> None:
        self._api_base = api_base
        self._timeout_s = timeout_s
        # "none" turns off "thinking" on reasoning models (qwen3.5 on CPU: ~25 s vs >180 s).
        self._reasoning_effort = reasoning_effort

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {}
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": json_schema.get("title", "output"), "schema": json_schema},
            }
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        # Without stream=True, acompletion returns a ModelResponse (never a stream wrapper).
        response: ModelResponse = await litellm.acompletion(  # type: ignore[assignment]
            model=model,
            messages=[m.model_dump() for m in messages],
            api_base=self._api_base,
            timeout=self._timeout_s,
            drop_params=True,  # skip params a provider doesn't support instead of failing
            **kwargs,
        )
        return LLMResponse(text=response.choices[0].message.content or "", model=model)
