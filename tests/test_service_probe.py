import pytest

from tests.service_probe import tcp_target


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:8333", ("localhost", 8333)),
        ("http://seaweedfs", ("seaweedfs", 80)),
        ("https://s3.eu-west-1.amazonaws.com", ("s3.eu-west-1.amazonaws.com", 443)),
        ("redis://localhost:6379/15", ("localhost", 6379)),
        ("redis://redis/0", ("redis", 6379)),
        ("rediss://cache.example.com/0", ("cache.example.com", 6379)),
    ],
)
def test_port_defaults_by_scheme(url: str, expected: tuple[str, int]) -> None:
    assert tcp_target(url) == expected


@pytest.mark.parametrize("url", ["", "None", "localhost:8333", "ftp://host"])
def test_unusable_urls_raise(url: str) -> None:
    with pytest.raises(ValueError):
        tcp_target(url)
