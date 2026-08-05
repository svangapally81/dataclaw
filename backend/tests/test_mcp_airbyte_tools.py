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
from app.services.mcp_executor import _airbyte_tool


@pytest.fixture(scope="module")
async def airbyte_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("airbyte")
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
                slug="airbyte",
                category="etl_orchestration",
                display_name="Airbyte",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"base_url": "http://airbyte", "api_key": "airbyte-key", "workspace_id": "workspace/1"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_airbyte_operational_reads_use_expected_request_shapes(
    airbyte_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if request.url.path == "/api/v1/connections/list":
            return httpx.Response(200, json={"connections": [{"connectionId": "connection/1"}]})
        if request.url.path == "/api/v1/jobs/list":
            assert body["configTypes"] == ["sync", "reset"]
            assert body["configId"] == "connection/1"
            return httpx.Response(200, json={"jobs": [{"id": 7}]})
        if request.url.path == "/api/v1/jobs/get":
            assert isinstance(body["id"], int)
            return httpx.Response(200, json={"job": {"id": body["id"]}, "attempts": [{"logs": {"logLines": ["failed"]}}]})
        if request.url.path == "/api/v1/state/get":
            return httpx.Response(200, json={"state": {"stream": "customers"}})
        if request.url.path == "/api/v1/sources/list":
            return httpx.Response(200, json={"sources": [{"sourceId": "source/1"}]})
        if request.url.path == "/api/v1/sources/get":
            return httpx.Response(200, json={"sourceId": body["sourceId"]})
        if request.url.path == "/api/v1/destinations/list":
            return httpx.Response(200, json={"destinations": [{"destinationId": "destination/1"}]})
        if request.url.path == "/api/v1/destinations/get":
            return httpx.Response(200, json={"destinationId": body["destinationId"]})
        if request.url.path == "/api/v1/workspaces/get":
            return httpx.Response(200, json={"workspaceId": body["workspaceId"]})
        if request.url.path == "/api/v1/connections/get":
            return httpx.Response(200, json={"connectionId": body["connectionId"], "syncCatalog": {"streams": []}})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://airbyte/.*").mock(side_effect=handler)
    session = airbyte_session

    connections = await _airbyte_tool(session, "read_list_connections", {}, "agent-1")
    jobs = await _airbyte_tool(session, "read_list_jobs", {"connection_id": "connection/1", "limit": 2}, "agent-1")
    job_logs = await _airbyte_tool(session, "read_get_job_logs", {"job_id": "7"}, "agent-1")
    state = await _airbyte_tool(session, "read_get_connection_state", {"connection_id": "connection/1"}, "agent-1")
    sources = await _airbyte_tool(session, "read_list_sources", {}, "agent-1")
    source = await _airbyte_tool(session, "read_get_source", {"source_id": "source/1"}, "agent-1")
    destinations = await _airbyte_tool(session, "read_list_destinations", {}, "agent-1")
    destination = await _airbyte_tool(session, "read_get_destination", {"destination_id": "destination/1"}, "agent-1")
    workspace = await _airbyte_tool(session, "read_get_workspace", {}, "agent-1")
    schema = await _airbyte_tool(session, "read_get_connection_schema", {"connection_id": "connection/1"}, "agent-1")

    assert connections["connections"] == [{"connectionId": "connection/1"}]
    assert jobs["jobs"] == [{"id": 7}]
    assert job_logs["logs"] == ["failed"]
    assert state["state"] == {"stream": "customers"}
    assert sources["sources"] == [{"sourceId": "source/1"}]
    assert source["source"] == {"sourceId": "source/1"}
    assert destinations["destinations"] == [{"destinationId": "destination/1"}]
    assert destination["destination"] == {"destinationId": "destination/1"}
    assert workspace["workspace"] == {"workspaceId": "workspace/1"}
    assert schema["schema"] == {"streams": []}
    assert ("POST", "http://airbyte/api/v1/connections/list", {"workspaceId": "workspace/1"}) in seen
    assert (
        "POST",
        "http://airbyte/api/v1/jobs/list",
        {"configId": "connection/1", "configTypes": ["sync", "reset"], "pagination": {"pageSize": 2}},
    ) in seen
    assert ("POST", "http://airbyte/api/v1/sources/get", {"sourceId": "source/1"}) in seen
    assert ("POST", "http://airbyte/api/v1/destinations/get", {"destinationId": "destination/1"}) in seen


@respx.mock
@pytest.mark.asyncio
async def test_airbyte_operational_writes_use_expected_request_shapes(
    airbyte_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if request.url.path == "/v1/jobs":
            return httpx.Response(200, json={"job": {"id": 1, "jobType": body["jobType"]}})
        if request.url.path == "/api/v1/connections/reset":
            return httpx.Response(200, json={"job": {"id": 2, "jobType": "reset"}})
        if request.url.path == "/api/v1/jobs/cancel":
            assert isinstance(body["id"], int)
            return httpx.Response(200, json={"job": {"id": body["id"], "status": "cancelled"}})
        if request.url.path == "/api/v1/connections/create":
            return httpx.Response(200, json={"connectionId": "connection/2", **body})
        if request.url.path == "/api/v1/connections/update":
            return httpx.Response(200, json={"connectionId": body["connectionId"], **body})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://airbyte/.*").mock(side_effect=handler)
    session = airbyte_session

    sync = await _airbyte_tool(session, "write_trigger_sync", {"connection_id": "connection/1"}, "agent-1")
    reset = await _airbyte_tool(session, "write_reset_connection", {"connection_id": "connection/1"}, "agent-1")
    cancelled = await _airbyte_tool(session, "write_cancel_job", {"job_id": "7"}, "agent-1")
    created = await _airbyte_tool(
        session,
        "write_create_connection",
        {"source_id": "source/1", "destination_id": "destination/1", "config": {"name": "daily"}},
        "agent-1",
    )
    updated = await _airbyte_tool(
        session,
        "write_update_connection",
        {"connection_id": "connection/1", "config": {"syncCatalog": {"streams": []}}},
        "agent-1",
    )
    disabled = await _airbyte_tool(session, "write_disable_connection", {"connection_id": "connection/1"}, "agent-1")
    enabled = await _airbyte_tool(session, "write_enable_connection", {"connection_id": "connection/1"}, "agent-1")

    assert sync["job"] == {"id": 1, "jobType": "sync"}
    assert reset["job"] == {"id": 2, "jobType": "reset"}
    assert cancelled["job"]["status"] == "cancelled"
    assert created["connection"]["connectionId"] == "connection/2"
    assert updated["connection"]["syncCatalog"] == {"streams": []}
    assert disabled["connection"]["status"] == "inactive"
    assert enabled["connection"]["status"] == "active"
    assert ("POST", "http://airbyte/v1/jobs", {"connectionId": "connection/1", "jobType": "sync"}) in seen
    assert ("POST", "http://airbyte/api/v1/connections/reset", {"connectionId": "connection/1"}) in seen
    assert ("POST", "http://airbyte/api/v1/jobs/cancel", {"id": 7}) in seen
    assert (
        "POST",
        "http://airbyte/api/v1/connections/create",
        {"name": "daily", "sourceId": "source/1", "destinationId": "destination/1"},
    ) in seen
    assert (
        "POST",
        "http://airbyte/api/v1/connections/update",
        {"syncCatalog": {"streams": []}, "connectionId": "connection/1"},
    ) in seen
    assert ("POST", "http://airbyte/api/v1/connections/update", {"connectionId": "connection/1", "status": "inactive"}) in seen
    assert ("POST", "http://airbyte/api/v1/connections/update", {"connectionId": "connection/1", "status": "active"}) in seen


@respx.mock
@pytest.mark.asyncio
async def test_airbyte_cloud_fallback_paths_encode_identifiers(
    airbyte_session: AsyncSession,
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.startswith("/api/v1/"):
            return httpx.Response(404, json={})
        if request.method == "POST" and request.url.path.startswith("/v1/jobs/"):
            return httpx.Response(405, json={})
        return httpx.Response(200, json={"id": "ok"})

    respx.route(url__regex=r"http://airbyte/.*").mock(side_effect=handler)
    session = airbyte_session

    await _airbyte_tool(session, "read_get_source", {"source_id": "source/1"}, "agent-1")
    await _airbyte_tool(session, "read_get_destination", {"destination_id": "destination/1"}, "agent-1")
    await _airbyte_tool(session, "read_get_connection_schema", {"connection_id": "connection/1"}, "agent-1")
    await _airbyte_tool(session, "write_cancel_job", {"job_id": "job/1"}, "agent-1")
    await _airbyte_tool(session, "write_disable_connection", {"connection_id": "connection/1"}, "agent-1")

    assert "http://airbyte/v1/sources/source%2F1" in seen
    assert "http://airbyte/v1/destinations/destination%2F1" in seen
    assert "http://airbyte/v1/connections/connection%2F1" in seen
    assert "http://airbyte/v1/jobs/job%2F1" in seen
