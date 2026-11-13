"""One real summary through LiteLLM + Ollama (~25 s on CPU).

Skipped whenever Ollama isn't reachable, also on CI: CI has no model server by design.
"""

import socket

import pytest

from housing_netherlands.config import Settings
from housing_netherlands.core.summarize import build_summary_request, summarize
from housing_netherlands.wiring import build_llm_client, extract_llm_params
from tests.fakes import make_listing
from tests.service_probe import tcp_target


@pytest.fixture
def settings() -> Settings:
    settings = Settings()
    try:
        socket.create_connection(tcp_target(settings.ollama_api_base or ""), timeout=1).close()
    except (OSError, ValueError) as exc:
        pytest.skip(f"Ollama not reachable at {settings.ollama_api_base!r} ({exc})")
    return settings


async def test_real_model_returns_valid_summary(settings: Settings) -> None:
    listing = make_listing(
        description=(
            "Ruim appartement aan het Zuidplein. Huur EUR 915 per maand, servicekosten EUR 45. "
            "Balkon op het zuiden. Niet roken, geen huisdieren. Beschikbaar per 1 december."
        )
    )
    result = await summarize(
        build_llm_client(settings),
        build_summary_request(listing, extract_llm_params(settings)),
    )
    assert result.summary.summary_en
    assert len(result.summary.key_facts) == 3
    assert result.attempts in (1, 2)
