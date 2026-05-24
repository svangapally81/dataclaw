from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

ACME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ACME_ROOT.parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.mcp_catalog import tools_for_slug  # noqa: E402
from tests.integration.acme.common import EXPECTED_ACME_CONNECTORS  # noqa: E402

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures.yml"


def load_fixture_matrix() -> dict:
    if not FIXTURES_PATH.exists():
        raise FileNotFoundError(f"Missing {FIXTURES_PATH}. Run make acme-fixtures.")
    return yaml.safe_load(FIXTURES_PATH.read_text()) or {}


def coverage_connector_slugs() -> list[str]:
    selected = os.getenv("ACME_COVERAGE_CONNECTOR")
    if not selected:
        return sorted(EXPECTED_ACME_CONNECTORS)
    if selected not in EXPECTED_ACME_CONNECTORS:
        known = ", ".join(sorted(EXPECTED_ACME_CONNECTORS))
        raise pytest.UsageError(f"Unknown ACME_COVERAGE_CONNECTOR={selected!r}. Acme MCP coverage connectors: {known}")
    return [selected]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if {"connector_slug", "tool_name", "tool_fixture"}.issubset(metafunc.fixturenames):
        matrix = load_fixture_matrix()
        rows = []
        ids = []
        for slug in coverage_connector_slugs():
            read_tools, write_tools = tools_for_slug(slug)
            for tool_name in [*read_tools, *write_tools]:
                rows.append((slug, tool_name, matrix.get(slug, {}).get(tool_name, {})))
                ids.append(f"{slug}.{tool_name}")
        metafunc.parametrize(("connector_slug", "tool_name", "tool_fixture"), rows, ids=ids)
