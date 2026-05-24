from __future__ import annotations

import json
import os

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import encrypt_json
from app.db.base import Base
from app.models.domain import Connector, Workspace
from app.services.mcp_executor import _dbt_tool


@pytest.fixture(scope="module")
async def dbt_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("dbt")
    os.environ["MASTER_KEY"] = "test-master-key-please-change"
    get_settings.cache_clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="Test")
        session.add(workspace)
        await session.flush()
        session.add(
            Connector(
                workspace_id=workspace.id,
                slug="dbt",
                category="etl_orchestration",
                display_name="dbt",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"base_url": "http://dbt", "api_token": "dbt-key", "job_id": "job/1"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


def _manifest() -> dict:
    return {
        "nodes": {
            "model.pkg.orders": {
                "unique_id": "model.pkg.orders",
                "resource_type": "model",
                "name": "orders",
                "alias": "fct_orders",
                "description": "Orders fact table",
                "raw_code": "select * from source_orders",
                "columns": {"id": {"name": "id", "description": "Order id"}},
            },
            "test.pkg.orders.not_null_id": {
                "unique_id": "test.pkg.orders.not_null_id",
                "resource_type": "test",
                "name": "not_null_orders_id",
            },
        },
        "exposures": {
            "exposure.pkg.revenue": {"unique_id": "exposure.pkg.revenue", "name": "Revenue dashboard"}
        },
    }


@respx.mock
@pytest.mark.asyncio
async def test_dbt_artifact_reads_use_cloud_run_artifacts(
    dbt_session: AsyncSession,
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/runs/":
            assert dict(request.url.params) == {"limit": "2", "job_definition_id": "job/1"}
            return httpx.Response(200, json={"data": [{"id": "run/1"}]})
        if str(request.url).endswith("/runs/run%2F1/artifacts/"):
            return httpx.Response(200, json={"data": ["manifest.json", "run_results.json", "catalog.json", "sources.json"]})
        if str(request.url).endswith("/runs/run%2F1/artifacts/manifest.json"):
            return httpx.Response(200, json=_manifest())
        if str(request.url).endswith("/runs/run%2F1/artifacts/run_results.json"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"unique_id": "model.pkg.orders", "status": "success"},
                        {"unique_id": "test.pkg.orders.not_null_id", "status": "pass"},
                    ]
                },
            )
        if str(request.url).endswith("/runs/run%2F1/artifacts/sources.json"):
            return httpx.Response(200, json={"results": [{"unique_id": "source.pkg.raw.orders", "status": "pass"}]})
        if str(request.url).endswith("/runs/run%2F1/artifacts/catalog.json"):
            return httpx.Response(200, json={"nodes": {"model.pkg.orders": {"stats": {"row_count": 3}}}})
        if str(request.url).startswith("http://dbt/runs/run%2F1/?"):
            assert dict(request.url.params) == {"include_related": '["debug_logs","run_steps"]'}
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "run/1",
                        "status": 10,
                        "run_steps": [{"logs": ["model failed: not_null_orders_id"]}],
                    }
                },
            )
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://dbt/.*").mock(side_effect=handler)
    session = dbt_session

    runs = await _dbt_tool(session, "read_list_runs", {"limit": 2, "job_definition_id": "job/1"}, "agent-1")
    artifacts = await _dbt_tool(
        session,
        "read_get_run_artifacts",
        {"run_id": "run/1", "paths": ["manifest.json"]},
        "agent-1",
    )
    manifest = await _dbt_tool(session, "read_get_manifest", {"run_id": "run/1"}, "agent-1")
    lineage = await _dbt_tool(session, "read_get_lineage", {"run_id": "run/1"}, "agent-1")
    models = await _dbt_tool(session, "read_list_models", {"run_id": "run/1"}, "agent-1")
    tests = await _dbt_tool(session, "read_list_tests", {"run_id": "run/1"}, "agent-1")
    test_results = await _dbt_tool(
        session,
        "read_get_test_results",
        {"run_id": "run/1", "unique_id": "test.pkg.orders.not_null_id"},
        "agent-1",
    )
    all_test_results = await _dbt_tool(session, "read_get_test_results", {"run_id": "run/1"}, "agent-1")
    freshness = await _dbt_tool(session, "read_get_source_freshness", {"run_id": "run/1"}, "agent-1")
    model_source = await _dbt_tool(session, "read_get_model_source", {"run_id": "run/1", "name": "orders"}, "agent-1")
    exposures = await _dbt_tool(session, "read_list_exposures", {"run_id": "run/1"}, "agent-1")
    docs = await _dbt_tool(session, "read_get_model_docs", {"run_id": "run/1", "unique_id": "model.pkg.orders"}, "agent-1")
    logs = await _dbt_tool(session, "read_get_run_logs", {"run_id": "run/1"}, "agent-1")

    assert runs["runs"] == [{"id": "run/1"}]
    assert artifacts["artifact_paths"] == ["manifest.json", "run_results.json", "catalog.json", "sources.json"]
    assert artifacts["artifacts"]["manifest.json"]["nodes"]["model.pkg.orders"]["name"] == "orders"
    assert manifest["manifest"]["nodes"]["model.pkg.orders"]["resource_type"] == "model"
    assert lineage["lineage"]["nodes"]["model.pkg.orders"]["name"] == "orders"
    assert models["models"][0]["unique_id"] == "model.pkg.orders"
    assert tests["tests"][0]["unique_id"] == "test.pkg.orders.not_null_id"
    assert test_results["results"] == [{"unique_id": "test.pkg.orders.not_null_id", "status": "pass"}]
    assert all_test_results["results"] == [{"unique_id": "test.pkg.orders.not_null_id", "status": "pass"}]
    assert freshness["freshness"]["results"][0]["status"] == "pass"
    assert model_source["source"] == "select * from source_orders"
    assert exposures["exposures"][0]["name"] == "Revenue dashboard"
    assert docs["docs"]["catalog"]["stats"]["row_count"] == 3
    assert logs["logs"] == ["model failed: not_null_orders_id"]
    assert "http://dbt/runs/run%2F1/artifacts/manifest.json" in seen
    assert any(url.startswith("http://dbt/runs/run%2F1/?") for url in seen)


@respx.mock
@pytest.mark.asyncio
async def test_dbt_writes_use_trigger_and_cancel_endpoints(
    dbt_session: AsyncSession,
    tmp_path,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if str(request.url).endswith("/jobs/job%2F2/run/"):
            return httpx.Response(200, json={"data": {"id": "run/2"}})
        if str(request.url).endswith("/jobs/job%2F1/run/"):
            return httpx.Response(200, json={"data": {"id": "run/1"}})
        if str(request.url).endswith("/runs/run%2F1/cancel/"):
            return httpx.Response(200, json={"data": {"id": "run/1", "status": 30}})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://dbt/.*").mock(side_effect=handler)
    session = dbt_session

    triggered = await _dbt_tool(session, "write_trigger_run", {"job_id": "job/2", "git_branch": "main"}, "agent-1")
    tested = await _dbt_tool(session, "write_trigger_test", {"job_id": "job/1"}, "agent-1")
    snapshot = await _dbt_tool(session, "write_trigger_snapshot", {}, "agent-1")
    seed = await _dbt_tool(session, "write_trigger_seed", {"job_id": "job/1"}, "agent-1")
    cancelled = await _dbt_tool(session, "write_cancel_run", {"run_id": "run/1"}, "agent-1")
    project_path = tmp_path / "dbt_project"
    created = await _dbt_tool(
        session,
        "write_create_model",
        {"project_path": str(project_path), "schema": "marts", "name": "orders_rollup", "sql": "select 1 as order_count"},
        "agent-1",
    )
    updated = await _dbt_tool(
        session,
        "write_update_model",
        {"project_path": str(project_path), "schema": "marts", "name": "orders_rollup", "sql": "select 2 as order_count"},
        "agent-1",
    )

    assert triggered["run"]["id"] == "run/2"
    assert tested["run"]["id"] == "run/1"
    assert snapshot["status"] == "triggered"
    assert seed["status"] == "triggered"
    assert cancelled["run"]["status"] == 30
    assert created["status"] == "created"
    assert updated["status"] == "updated"
    assert (project_path / "models" / "marts" / "orders_rollup.sql").read_text() == "select 2 as order_count\n"
    assert ("POST", "http://dbt/runs/run%2F1/cancel/", {}) in seen
    assert any(url == "http://dbt/jobs/job%2F2/run/" and body["git_branch"] == "main" for _, url, body in seen)
    assert any(url == "http://dbt/jobs/job%2F1/run/" and body["steps_override"] == ["dbt test"] for _, url, body in seen)
    assert any(url == "http://dbt/jobs/job%2F1/run/" and body["steps_override"] == ["dbt snapshot"] for _, url, body in seen)
    assert any(url == "http://dbt/jobs/job%2F1/run/" and body["steps_override"] == ["dbt seed"] for _, url, body in seen)
