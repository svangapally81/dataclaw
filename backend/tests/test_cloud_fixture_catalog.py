from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from tests.support.http_fixture_replay import load_http_fixture_manifest, register_http_fixtures

REQUIRED_FIXTURES = {
    "snowflake": "query_history.json",
    "redshift": "query_history.json",
    "databricks": "jobs_list.json",
    "fivetran": "connectors.json",
    "notion": "search_pages.json",
    "google_docs": "documents.json",
    "quip": "threads.json",
}
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "integration" / "fixtures"
RECORD_PATHS = {
    "snowflake": ("queries",),
    "redshift": ("queries",),
    "databricks": ("jobs",),
    "fivetran": ("data", "items"),
    "notion": ("results",),
    "google_docs": ("files",),
    "quip": ("threads",),
}


def _records(connector: str, payload: dict) -> list[dict]:
    value = payload
    for key in RECORD_PATHS[connector]:
        value = value[key]
    assert isinstance(value, list)
    return value


def test_cloud_connector_fixture_catalog_is_present_and_parseable() -> None:
    for connector, filename in REQUIRED_FIXTURES.items():
        path = FIXTURE_ROOT / connector / filename
        assert path.exists(), f"Missing fixture for {connector}: {path}"
        payload = json.loads(path.read_text())
        assert isinstance(payload, dict)
        assert payload
        records = _records(connector, payload)
        assert len(records) >= 3
        assert all(isinstance(record, dict) and record for record in records)


def test_cloud_connector_fixtures_include_success_and_failure_context() -> None:
    operational_payload = ""
    for connector, filename in REQUIRED_FIXTURES.items():
        payload = json.loads((FIXTURE_ROOT / connector / filename).read_text())
        operational_payload += json.dumps(payload).lower()

    for expected in ("success", "failed", "malformed", "warning", "migration", "runbook"):
        assert expected in operational_payload


def test_http_fixture_replay_manifest_covers_required_cloud_connectors() -> None:
    routes = load_http_fixture_manifest(FIXTURE_ROOT)
    assert {route.connector for route in routes} == set(REQUIRED_FIXTURES)
    for route in routes:
        assert (FIXTURE_ROOT / route.fixture).exists()


def test_http_fixture_replay_matches_exact_method_and_url() -> None:
    with respx.mock(assert_all_mocked=True) as router:
        registered = register_http_fixtures(router, FIXTURE_ROOT)

        for route in load_http_fixture_manifest(FIXTURE_ROOT):
            response = httpx.request(route.method, route.url)
            response.raise_for_status()
            assert response.json()

        assert all(route.called for route in registered)
        with pytest.raises(AssertionError):
            httpx.get("https://api.fivetran.com/v1/connectors/unrecorded")
