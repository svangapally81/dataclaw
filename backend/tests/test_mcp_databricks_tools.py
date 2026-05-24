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
from app.services.mcp_executor import McpExecutionError, _databricks_tool


@pytest.fixture(scope="module")
async def databricks_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("databricks")
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
                slug="databricks",
                category="data_store",
                display_name="Databricks",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"workspace_url": "http://databricks", "token": "db-token", "warehouse_id": "wh-1"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


def _statement_payload(rows: list[list], columns: list[str]) -> dict:
    return {
        "statement_id": "stmt-1",
        "manifest": {"schema": {"columns": [{"name": name} for name in columns]}},
        "result": {"data_array": rows},
    }


@respx.mock
@pytest.mark.asyncio
async def test_databricks_matrix_reads_and_writes(databricks_session: AsyncSession) -> None:
    seen: list[tuple[str, str, dict, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, request.url.path, dict(request.url.params), body))
        assert request.headers["Authorization"] == "Bearer db-token"
        if request.url.path == "/api/2.0/clusters/list":
            return httpx.Response(200, json={"clusters": [{"cluster_id": "cluster-1"}]})
        if request.url.path == "/api/2.0/sql/warehouses":
            return httpx.Response(200, json={"warehouses": [{"id": "wh-1"}]})
        if request.url.path == "/api/2.0/unity-catalog/tables/main.analytics.customers":
            return httpx.Response(200, json={"full_name": "main.analytics.customers"})
        if request.url.path == "/api/2.0/workspace/export":
            return httpx.Response(200, json={"path": request.url.params["path"], "content": "cHJpbnQoMSk="})
        if request.url.path == "/api/2.0/jobs/runs/get-output":
            return httpx.Response(200, json={"metadata": {"run_id": int(request.url.params["run_id"])}, "logs": "ok"})
        if request.url.path == "/api/2.0/jobs/run-now":
            return httpx.Response(200, json={"run_id": 10})
        if request.url.path == "/api/2.0/jobs/runs/submit":
            return httpx.Response(200, json={"run_id": 11})
        if request.url.path == "/api/2.0/clusters/start":
            return httpx.Response(200, json={})
        if request.url.path == "/api/2.0/clusters/delete":
            return httpx.Response(200, json={})
        if request.url.path == "/api/2.1/unity-catalog/permissions/table/main.analytics.customers":
            return httpx.Response(200, json={"privilege_assignments": []})
        if request.url.path == "/api/2.0/sql/statements":
            statement = body["statement"]
            if "system.access.table_lineage" in statement:
                return httpx.Response(200, json=_statement_payload([["a", "b", "JOB", "1", "2026-05-01"]], ["source_table_full_name", "target_table_full_name", "entity_type", "entity_id", "event_time"]))
            if "system.query.history" in statement:
                return httpx.Response(200, json=_statement_payload([["stmt", "user", "2026-05-01", "2026-05-01", "FINISHED", "select 1"]], ["statement_id", "executed_by", "start_time", "end_time", "status", "statement_text"]))
            return httpx.Response(200, json={"statement_id": "stmt-write", "manifest": {"schema": {"columns": []}}, "result": {"data_array": []}})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://databricks/.*").mock(side_effect=handler)
    session = databricks_session

    clusters = await _databricks_tool(session, "read_list_clusters", {}, "agent-1")
    warehouses = await _databricks_tool(session, "read_list_warehouses", {}, "agent-1")
    notebook = await _databricks_tool(session, "read_get_notebook", {"path": "/Shared/demo"}, "agent-1")
    logs = await _databricks_tool(session, "read_get_run_logs", {"run_id": 7}, "agent-1")
    asset = await _databricks_tool(session, "read_get_unity_asset", {"full_name": "main.analytics.customers"}, "agent-1")
    lineage = await _databricks_tool(session, "read_get_lineage", {"asset": "main.analytics.customers"}, "agent-1")
    history = await _databricks_tool(session, "read_get_query_history", {"since": "2026-05-01T00:00:00Z"}, "agent-1")
    triggered = await _databricks_tool(session, "write_trigger_job", {"job_id": 9}, "agent-1")
    notebook_run = await _databricks_tool(session, "write_run_notebook", {"path": "/Shared/demo", "cluster_id": "cluster-1", "params": {"env": "test"}}, "agent-1")
    started = await _databricks_tool(session, "write_start_cluster", {"cluster_id": "cluster-1"}, "agent-1")
    stopped = await _databricks_tool(session, "write_stop_cluster", {"cluster_id": "cluster-1"}, "agent-1")
    view = await _databricks_tool(session, "write_create_view", {"view": "main.analytics.active_customers", "select_sql": "select * from main.analytics.customers"}, "agent-1")
    grants = await _databricks_tool(
        session,
        "write_update_unity_grants",
        {"full_name": "main.analytics.customers", "changes": [{"principal": "analysts", "add": ["SELECT"]}]},
        "agent-1",
    )

    assert clusters["clusters"] == [{"cluster_id": "cluster-1"}]
    assert warehouses["warehouses"] == [{"id": "wh-1"}]
    assert notebook["notebook"]["content"] == "cHJpbnQoMSk="
    assert logs["run_output"]["logs"] == "ok"
    assert asset["asset"]["full_name"] == "main.analytics.customers"
    assert lineage["lineage"][0]["entity_type"] == "JOB"
    assert history["queries"][0]["statement_id"] == "stmt"
    assert triggered["run"]["run_id"] == 10
    assert notebook_run["run"]["run_id"] == 11
    assert started["status"] == "executed"
    assert stopped["status"] == "executed"
    assert view["statement_id"] == "stmt-write"
    assert grants["permissions"] == {"privilege_assignments": []}
    assert any(item[3].get("notebook_task", {}).get("base_parameters") == {"env": "test"} for item in seen)
    assert any("create or replace view main.analytics.active_customers" in item[3].get("statement", "") for item in seen)


@respx.mock
@pytest.mark.asyncio
async def test_databricks_query_history_rejects_invalid_since(databricks_session: AsyncSession) -> None:
    respx.route(url__regex=r"http://databricks/.*").mock(return_value=httpx.Response(500, json={}))

    with pytest.raises(McpExecutionError, match="ISO-8601"):
        await _databricks_tool(databricks_session, "read_get_query_history", {"since": "x' or 1=1 --"}, "agent-1")
