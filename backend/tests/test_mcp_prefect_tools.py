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
from app.services.mcp_executor import _prefect_tool


@pytest.fixture(scope="module")
async def prefect_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("prefect")
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
                slug="prefect",
                category="etl_orchestration",
                display_name="Prefect",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"base_url": "http://prefect", "api_key": "prefect-key"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_prefect_operational_reads_use_expected_paths_and_bounded_payloads(
    prefect_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if request.url.path == "/api/flows/filter":
            return httpx.Response(200, json=[{"id": "flow/1"}])
        if request.url.path == "/api/flow_runs/run/1":
            return httpx.Response(200, json={"id": "run/1", "state": "FAILED"})
        if request.url.path == "/api/logs/filter":
            return httpx.Response(200, json=[{"message": "boom"}])
        if request.url.path == "/api/flow_runs/filter":
            return httpx.Response(200, json=[{"id": "run/2"}])
        if request.url.path == "/api/deployments/filter":
            return httpx.Response(200, json=[{"id": "deployment/1"}])
        if request.url.path == "/api/deployments/deployment/1":
            return httpx.Response(200, json={"id": "deployment/1"})
        if request.url.path == "/api/task_runs/task/1":
            return httpx.Response(200, json={"id": "task/1"})
        if request.url.path == "/api/work_pools/filter":
            return httpx.Response(200, json=[{"name": "default"}])
        if request.url.path == "/api/block_types/slug/secret/block_documents/name/api-key":
            return httpx.Response(200, json={"name": "api-key", "data": {"value": "redacted"}})
        if request.url.path == "/api/concurrency_limits/tag/orders":
            return httpx.Response(200, json={"tag": "orders", "concurrency_limit": 5})
        if request.url.path == "/api/artifacts/filter":
            return httpx.Response(200, json=[{"key": "summary"}])
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://prefect/.*").mock(side_effect=handler)
    session = prefect_session

    flows = await _prefect_tool(session, "read_list_flows", {"limit": 2000}, "agent-1")
    run = await _prefect_tool(session, "read_get_run", {"run_id": "run/1"}, "agent-1")
    logs = await _prefect_tool(session, "read_get_run_logs", {"run_id": "run/1", "limit": 2}, "agent-1")
    task_logs = await _prefect_tool(session, "read_get_task_logs", {"flow_run_id": "run/1", "task_run_id": "task/1", "limit": 2}, "agent-1")
    flow_runs = await _prefect_tool(
        session,
        "read_list_flow_runs",
        {"flow_id": "flow/1", "since": "2026-05-01T00:00:00Z", "limit": 3},
        "agent-1",
    )
    deployments = await _prefect_tool(session, "read_list_deployments", {}, "agent-1")
    deployment = await _prefect_tool(session, "read_get_deployment", {"deployment_id": "deployment/1"}, "agent-1")
    task_run = await _prefect_tool(session, "read_get_task_run", {"task_run_id": "task/1"}, "agent-1")
    work_pools = await _prefect_tool(session, "read_list_work_pools", {}, "agent-1")
    block = await _prefect_tool(session, "read_get_block", {"name": "api-key", "block_type_slug": "secret"}, "agent-1")
    concurrency = await _prefect_tool(session, "read_get_concurrency_limit", {"tag": "orders"}, "agent-1")
    artifacts = await _prefect_tool(session, "read_list_artifacts", {"flow_run_id": "run/1"}, "agent-1")

    assert flows["flows"] == [{"id": "flow/1"}]
    assert run["run"]["state"] == "FAILED"
    assert logs["logs"] == [{"message": "boom"}]
    assert task_logs["logs"] == [{"message": "boom"}]
    assert flow_runs["flow_runs"] == [{"id": "run/2"}]
    assert deployments["deployments"] == [{"id": "deployment/1"}]
    assert deployment["deployment"] == {"id": "deployment/1"}
    assert task_run["task_run"] == {"id": "task/1"}
    assert work_pools["work_pools"] == [{"name": "default"}]
    assert block["block"]["name"] == "api-key"
    assert concurrency["concurrency_limit"]["concurrency_limit"] == 5
    assert artifacts["artifacts"] == [{"key": "summary"}]
    assert ("POST", "http://prefect/api/flows/filter", {"limit": 1000}) in seen
    assert ("GET", "http://prefect/api/flow_runs/run%2F1", {}) in seen
    assert (
        "POST",
        "http://prefect/api/logs/filter",
        {"logs": {"flow_run_id": {"any_": ["run/1"]}}, "limit": 2, "sort": "TIMESTAMP_DESC"},
    ) in seen
    assert (
        "POST",
        "http://prefect/api/logs/filter",
        {"logs": {"flow_run_id": {"any_": ["run/1"]}, "task_run_id": {"any_": ["task/1"]}}, "limit": 2, "sort": "TIMESTAMP_DESC"},
    ) in seen
    assert (
        "POST",
        "http://prefect/api/flow_runs/filter",
        {
            "limit": 3,
            "sort": "START_TIME_DESC",
            "flows": {"id": {"any_": ["flow/1"]}},
            "flow_runs": {"start_time": {"after_": "2026-05-01T00:00:00Z"}},
        },
    ) in seen
    assert ("GET", "http://prefect/api/deployments/deployment%2F1", {}) in seen
    assert ("GET", "http://prefect/api/task_runs/task%2F1", {}) in seen


@respx.mock
@pytest.mark.asyncio
async def test_prefect_operational_writes_use_expected_paths_and_payloads(
    prefect_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if request.url.path.endswith("/create_flow_run"):
            return httpx.Response(200, json={"id": "created"})
        if request.url.path == "/api/deployments":
            return httpx.Response(200, json={"id": "deployment/2"})
        if request.url.path.startswith("/api/deployments/") and request.method == "PATCH":
            return httpx.Response(204)
        if request.url.path.endswith("/set_state"):
            return httpx.Response(200, json={"status": "ACCEPT"})
        if str(request.url) == "http://prefect/api/blocks/block%2F1":
            return httpx.Response(200, json={"id": "block/1", "data": body["data"]})
        if request.url.path == "/api/concurrency_limits/tag/orders/reset":
            return httpx.Response(200, json={"tag": "orders", "concurrency_limit": body["limit"]})
        if request.url.path.startswith("/api/deployments/") and request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://prefect/.*").mock(side_effect=handler)
    session = prefect_session

    triggered = await _prefect_tool(
        session,
        "write_trigger_flow_run",
        {"deployment_id": "deployment/1", "name": "manual", "parameters": {"date": "2026-05-01"}},
        "agent-1",
    )
    created = await _prefect_tool(
        session,
        "write_create_deployment",
        {"name": "daily", "flow_id": "flow/1", "entrypoint": "flows.py:daily"},
        "agent-1",
    )
    paused = await _prefect_tool(session, "write_pause_deployment", {"deployment_id": "deployment/1"}, "agent-1")
    resumed = await _prefect_tool(session, "write_resume_deployment", {"deployment_id": "deployment/1"}, "agent-1")
    cancelled = await _prefect_tool(session, "write_cancel_flow_run", {"run_id": "run/1"}, "agent-1")
    block = await _prefect_tool(session, "write_set_block", {"block_id": "block/1", "data": {"value": "new"}}, "agent-1")
    concurrency = await _prefect_tool(session, "write_set_concurrency_limit", {"tag": "orders", "limit": 3}, "agent-1")
    deleted = await _prefect_tool(session, "write_delete_deployment", {"deployment_id": "deployment/1"}, "agent-1")

    assert triggered["run"] == {"id": "created"}
    assert created["deployment"] == {"id": "deployment/2"}
    assert paused["paused"] is True
    assert paused["deployment"] is None
    assert resumed["paused"] is False
    assert resumed["deployment"] is None
    assert cancelled["status"] == "cancelled"
    assert block["block"]["data"] == {"value": "new"}
    assert concurrency["concurrency_limit"]["concurrency_limit"] == 3
    assert deleted["status"] == "deleted"
    assert (
        "POST",
        "http://prefect/api/deployments/deployment%2F1/create_flow_run",
        {"name": "manual", "parameters": {"date": "2026-05-01"}},
    ) in seen
    assert (
        "POST",
        "http://prefect/api/deployments",
        {"name": "daily", "flow_id": "flow/1", "entrypoint": "flows.py:daily"},
    ) in seen
    assert ("PATCH", "http://prefect/api/deployments/deployment%2F1", {"paused": True}) in seen
    assert ("PATCH", "http://prefect/api/deployments/deployment%2F1", {"paused": False}) in seen
    assert (
        "POST",
        "http://prefect/api/flow_runs/run%2F1/set_state",
        {"state": {"type": "CANCELLING", "name": "Cancelling"}},
    ) in seen
    assert ("PATCH", "http://prefect/api/blocks/block%2F1", {"data": {"value": "new"}}) in seen
    assert ("POST", "http://prefect/api/concurrency_limits/tag/orders/reset", {"limit": 3}) in seen
    assert ("DELETE", "http://prefect/api/deployments/deployment%2F1", {}) in seen


@respx.mock
@pytest.mark.asyncio
async def test_prefect_pause_deployment_falls_back_for_prefect_two_payload(
    prefect_session: AsyncSession,
) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append(body)
        if body == {"paused": True}:
            return httpx.Response(422, json={"detail": "unknown field"})
        return httpx.Response(200, json={"id": "deployment/1", "is_schedule_active": body["is_schedule_active"]})

    respx.route(url__regex=r"http://prefect/.*").mock(side_effect=handler)
    result = await _prefect_tool(
        prefect_session,
        "write_pause_deployment",
        {"deployment_id": "deployment/1"},
        "agent-1",
    )

    assert result["deployment"]["is_schedule_active"] is False
    assert seen == [{"paused": True}, {"is_schedule_active": False}]
