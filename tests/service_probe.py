"""Where to probe a service URL with a TCP connect (used by the integration fixtures)."""

from urllib.parse import urlsplit

DEFAULT_PORTS = {"http": 80, "https": 443, "redis": 6379, "rediss": 6379}


def tcp_target(url: str) -> tuple[str, int]:
    """Return (host, port) for `url`; the port defaults by scheme. Raises ValueError if unusable."""
    parsed = urlsplit(url)
    if not parsed.hostname:
        raise ValueError(f"no host in service URL {url!r}")
    if parsed.port is not None:
        return parsed.hostname, parsed.port
    if parsed.scheme not in DEFAULT_PORTS:
        raise ValueError(f"no port in {url!r} and no default for scheme {parsed.scheme!r}")
    return parsed.hostname, DEFAULT_PORTS[parsed.scheme]
