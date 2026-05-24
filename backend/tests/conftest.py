from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def explicit_vector_test_double(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATACLAW_VECTOR_TEST_DOUBLE", "true")
    monkeypatch.setenv("DATACLAW_TEST_AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setenv("DATACLAW_BCRYPT_ROUNDS", "4")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow release-gate tests that require live services",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--runslow"):
        return
    skip_slow = pytest.mark.skip(reason="pass --runslow to run this release-gate test")
    for item in items:
        if "runslow" in item.keywords:
            item.add_marker(skip_slow)
