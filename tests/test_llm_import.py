"""LiteLLM import behaviour, checked in fresh interpreters (this process already loaded it)."""

import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator

import pytest

# Variables that would leak the developer's own setup into the child interpreter.
_STRIP = ("LITELLM_LOCAL_MODEL_COST_MAP", "LITELLM_MODEL_COST_MAP_URL")


def _run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    child_env = {k: v for k, v in os.environ.items() if k not in _STRIP} | env
    return subprocess.run(
        [sys.executable, "-c", code],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )


@pytest.fixture
def proxy_connections() -> Iterator[tuple[str, list[int]]]:
    """A local 'proxy' that only counts connection attempts (and then drops them)."""
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(0.2)
    hits: list[int] = []
    stop = threading.Event()

    def accept_loop() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            hits.append(1)
            conn.close()

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.getsockname()[1]}", hits
    stop.set()
    thread.join(2)
    server.close()


def test_wiring_loads_litellm_lazily_and_without_network(
    proxy_connections: tuple[str, list[int]],
) -> None:
    proxy, hits = proxy_connections
    code = (
        "import os, sys\n"
        "from housing_netherlands.config import Settings\n"
        "from housing_netherlands.wiring import build_llm_client\n"
        "print('litellm' in sys.modules)\n"  # importing wiring: not loaded
        "build_llm_client(Settings())\n"
        "print('litellm' in sys.modules)\n"  # building the client: loaded now
        "print(os.environ['LITELLM_LOCAL_MODEL_COST_MAP'])\n"
    )
    out = _run(code, HTTPS_PROXY=proxy, HTTP_PROXY=proxy, NO_PROXY="")
    assert out.stdout.split() == ["False", "True", "True"]
    assert hits == []  # no cost-map fetch went out


def test_without_the_default_litellm_would_fetch(proxy_connections: tuple[str, list[int]]) -> None:
    # Guards the test above: proves the proxy really sees litellm's fetch when not disabled.
    proxy, hits = proxy_connections
    _run("import litellm", HTTPS_PROXY=proxy, HTTP_PROXY=proxy, NO_PROXY="")
    assert hits, "expected litellm to try fetching the remote cost map"
