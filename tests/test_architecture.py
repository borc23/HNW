"""Import boundaries: core never imports infrastructure; only `adapters` and `wiring` do."""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "housing_netherlands"

INFRA = {
    "aioboto3",
    "arq",
    "asyncpg",
    "boto3",
    "botocore",
    "curl_cffi",
    "geoalchemy2",
    "httpx",
    "litellm",
    "pyhuurwoningen",
    "redis",
    "sqlalchemy",
}
WEB = {"fastapi", "jinja2", "starlette"}
OWN = "housing_netherlands"

# package -> top-level modules it must not import
FORBIDDEN: dict[str, set[str]] = {
    "core": INFRA | WEB | {f"{OWN}.adapters", f"{OWN}.api", f"{OWN}.workers", f"{OWN}.wiring"},
    "api": INFRA | {f"{OWN}.adapters", f"{OWN}.workers"},
    "workers": INFRA | WEB | {f"{OWN}.adapters", f"{OWN}.api"},
}


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def violations(source: str, forbidden: set[str]) -> set[str]:
    return {
        mod
        for mod in imported_modules(source)
        if any(mod == f or mod.startswith(f"{f}.") for f in forbidden)
    }


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_package_respects_import_boundaries(package: str) -> None:
    pkg_dir = PACKAGE_ROOT / package
    if not pkg_dir.exists():
        pytest.skip(f"{package}/ not created yet")
    found = {
        f"{path.relative_to(PACKAGE_ROOT)}: {mod}"
        for path in pkg_dir.rglob("*.py")
        for mod in violations(path.read_text(), FORBIDDEN[package])
    }
    assert not found, f"forbidden imports: {sorted(found)}"


def test_guard_detects_forbidden_imports() -> None:
    source = (
        "import redis\n"
        "from sqlalchemy.orm import Session\n"
        "from housing_netherlands.adapters import x\n"
    )
    assert violations(source, FORBIDDEN["core"]) == {
        "redis",
        "sqlalchemy.orm",
        "housing_netherlands.adapters",
    }


def test_guard_allows_core_and_stdlib() -> None:
    source = "import json\nfrom housing_netherlands.core.models import Listing\nimport pydantic\n"
    assert violations(source, FORBIDDEN["core"]) == set()
