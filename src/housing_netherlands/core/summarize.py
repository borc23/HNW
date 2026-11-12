"""Listing summary use-case: versioned prompt -> LLM -> validated `ListingSummary`.

The output is validated against the schema; one invalid answer gets a single retry with the
validation error fed back, and a second invalid answer raises `LLMOutputInvalid`.
"""

import hashlib
import json
from dataclasses import dataclass

from pydantic import ValidationError

from housing_netherlands.core.errors import LLMOutputInvalid
from housing_netherlands.core.models import Listing, ListingSummary, LLMMessage
from housing_netherlands.core.ports import LLMClient
from housing_netherlands.core.prompts import summary_v1

MAX_ATTEMPTS = 2  # first answer + one retry


@dataclass(frozen=True)
class SummaryRequest:
    """Everything that determines the LLM output; `content_hash` is the cache key."""

    prompt_version: str
    messages: list[LLMMessage]
    content_hash: str


@dataclass(frozen=True)
class SummaryResult:
    summary: ListingSummary
    model: str
    attempts: int


def content_hash(prompt_version: str, messages: list[LLMMessage]) -> str:
    """sha256 over the prompt version and the exact messages sent to the model."""
    payload = json.dumps(
        {"v": prompt_version, "m": [m.model_dump() for m in messages]},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def build_summary_request(listing: Listing) -> SummaryRequest:
    messages = summary_v1.build_messages(listing)
    return SummaryRequest(
        prompt_version=summary_v1.PROMPT_VERSION,
        messages=messages,
        content_hash=content_hash(summary_v1.PROMPT_VERSION, messages),
    )


async def summarize(llm: LLMClient, request: SummaryRequest, *, model: str) -> SummaryResult:
    schema = summary_v1.OUTPUT_SCHEMA.model_json_schema()
    messages = list(request.messages)
    errors: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = await llm.complete(messages, model=model, json_schema=schema)
        try:
            summary = summary_v1.OUTPUT_SCHEMA.model_validate_json(response.text)
        except ValidationError as exc:
            error = _short_errors(exc)
            errors.append(error)
            messages = [
                *messages,
                LLMMessage(role="assistant", content=response.text),
                LLMMessage(
                    role="user",
                    content=f"That reply was invalid: {error}. "
                    "Reply again with JSON only, matching the requested shape exactly.",
                ),
            ]
            continue
        return SummaryResult(summary=summary, model=response.model, attempts=attempt)
    raise LLMOutputInvalid(request.prompt_version, errors)


def _short_errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'output'}: {e['msg']}" for e in exc.errors()
    )[:500]
