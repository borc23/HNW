import json

import pytest

from housing_netherlands.core.errors import LLMOutputInvalid
from housing_netherlands.core.models import ListingSummary
from housing_netherlands.core.prompts import summary_v1
from housing_netherlands.core.summarize import (
    build_summary_request,
    content_hash,
    summarize,
)
from tests.fakes import FakeLLMClient
from tests.test_core_models import make_listing

MODEL = "ollama_chat/qwen3.5:4b"
VALID = json.dumps(
    {"summary_en": "Bright 3-room flat.", "key_facts": ["EUR 915/month", "50 m2", "balcony"]}
)


# --- prompt -------------------------------------------------------------------------------


def test_prompt_contains_listing_facts_but_not_url_or_source() -> None:
    listing = make_listing(description="Mooi appartement met balkon.")
    user = summary_v1.build_messages(listing)[1].content
    assert "Appartement Zuidplein" in user
    assert "915 EUR/month" in user and "50.0 m2" in user
    assert "Mooi appartement met balkon." in user
    assert listing.url not in user and listing.source not in user


def test_prompt_marks_missing_fields_and_truncates_long_descriptions() -> None:
    long_text = "x" * (summary_v1.MAX_DESCRIPTION_CHARS + 500)
    user = summary_v1.build_messages(make_listing(price_eur=None, description=long_text))[1].content
    assert "Rent: unknown" in user
    assert "x" * summary_v1.MAX_DESCRIPTION_CHARS in user
    assert "x" * (summary_v1.MAX_DESCRIPTION_CHARS + 1) not in user


# --- content hash (the LLM cache key) -----------------------------------------------------


def test_hash_is_stable_for_same_input() -> None:
    assert build_summary_request(make_listing()).content_hash == (
        build_summary_request(make_listing()).content_hash
    )


def test_same_home_on_another_site_has_same_hash() -> None:
    a = make_listing()
    b = make_listing(source="pararius", url="https://www.pararius.com/x", source_listing_id="p1")
    assert build_summary_request(a).content_hash == build_summary_request(b).content_hash


@pytest.mark.parametrize(
    "change", [{"price_eur": 950}, {"description": "Nieuw!"}, {"title": "Other"}]
)
def test_hash_changes_when_prompt_input_changes(change: dict) -> None:
    assert build_summary_request(make_listing()).content_hash != (
        build_summary_request(make_listing(**change)).content_hash
    )


def test_hash_changes_with_prompt_version() -> None:
    messages = summary_v1.build_messages(make_listing())
    assert content_hash("summary-v1", messages) != content_hash("summary-v2", messages)


# --- summarize: validate + retry once -----------------------------------------------------


async def test_valid_first_answer() -> None:
    llm = FakeLLMClient(VALID)
    result = await summarize(llm, build_summary_request(make_listing()), model=MODEL)
    assert result.summary == ListingSummary.model_validate_json(VALID)
    assert (result.attempts, result.model) == (1, MODEL)
    assert len(llm.calls) == 1


async def test_schema_is_sent_to_the_model() -> None:
    llm = FakeLLMClient(VALID)
    await summarize(llm, build_summary_request(make_listing()), model=MODEL)
    schema = llm.schemas[0]
    assert schema is not None
    assert set(schema["required"]) == {"summary_en", "key_facts"}
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "bad",
    [
        "not json at all",
        '{"summary_en": "x", "key_facts": ["only", "two"]}',
        '{"summary_en": "x", "key_facts": ["a", "b", "c"], "extra": 1}',
        '{"summary_en": "", "key_facts": ["a", "b", "c"]}',
    ],
)
async def test_invalid_then_valid_retries_once_with_feedback(bad: str) -> None:
    llm = FakeLLMClient(bad, VALID)
    result = await summarize(llm, build_summary_request(make_listing()), model=MODEL)
    assert result.attempts == 2
    retry = llm.calls[1]
    assert retry[-2].role == "assistant" and retry[-2].content == bad
    assert retry[-1].role == "user" and "invalid" in retry[-1].content


async def test_two_invalid_answers_raise() -> None:
    llm = FakeLLMClient("nope", '{"summary_en": "x", "key_facts": []}')
    with pytest.raises(LLMOutputInvalid) as exc_info:
        await summarize(llm, build_summary_request(make_listing()), model=MODEL)
    assert len(llm.calls) == 2  # never a third call
    assert exc_info.value.prompt_version == "summary-v1"
    assert len(exc_info.value.errors) == 2
