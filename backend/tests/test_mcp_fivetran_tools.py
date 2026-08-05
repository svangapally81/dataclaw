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
from app.services.mcp_executor import _fivetran_tool


@pytest.fixture(scope="module")
async def fivetran_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("fivetran")
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
                slug="fivetran",
                category="etl_orchestration",
                display_name="Fivetran",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"api_key": "fivetran-key", "api_secret": "fivetran-secret"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_fivetran_operational_reads_use_expected_paths_and_params(
    fivetran_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), dict(request.url.params)))
        if request.url.path == "/v1/connectors":
            return httpx.Response(200, json={"data": {"items": [{"id": "connector/1"}]}})
        if request.url.path == "/v1/connectors/connector/1":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "connector/1",
                        "status": {
                            "setup_state": "connected",
                            "tasks": [{"message": "fix schema"}],
                            "warnings": [{"message": "slow sync"}],
                            "sync_state": "scheduled",
                        },
                        "succeeded_at": "2026-05-10T00:00:00Z",
                        "failed_at": "2026-05-11T00:00:00Z",
                    }
                },
            )
        if request.url.path == "/v1/connectors/connector/1/schemas":
            return httpx.Response(200, json={"data": {"schemas": {"public": {}}}})
        if request.url.path == "/v1/metadata/connectors/connector/1":
            return httpx.Response(200, json={"data": {"tables": [{"name": "orders"}]}})
        if request.url.path == "/v1/connectors/connector/1/usage":
            return httpx.Response(200, json={"data": {"rows_synced": 42}})
        if request.url.path == "/v1/destinations":
            return httpx.Response(200, json={"data": {"items": [{"id": "destination/1"}]}})
        if request.url.path == "/v1/destinations/destination/1":
            return httpx.Response(200, json={"data": {"id": "destination/1"}})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"https://api\.fivetran\.com/.*").mock(side_effect=handler)
    session = fivetran_session

    connectors = await _fivetran_tool(session, "read_list_connectors", {}, "agent-1")
    logs = await _fivetran_tool(session, "read_get_connector_logs", {"connector_id": "connector/1", "limit": 3}, "agent-1")
    status = await _fivetran_tool(session, "read_get_connector_status", {"connector_id": "connector/1"}, "agent-1")
    schema = await _fivetran_tool(session, "read_get_connector_schema", {"connector_id": "connector/1"}, "agent-1")
    destinations = await _fivetran_tool(session, "read_list_destinations", {}, "agent-1")
    destination = await _fivetran_tool(session, "read_get_destination", {"destination_id": "destination/1"}, "agent-1")
    metadata = await _fivetran_tool(session, "read_get_metadata", {"connector_id": "connector/1"}, "agent-1")
    volume = await _fivetran_tool(session, "read_get_data_volume", {"connector_id": "connector/1", "since": "2026-05-01"}, "agent-1")
    history = await _fivetran_tool(session, "read_get_sync_history", {"connector_id": "connector/1", "limit": 5}, "agent-1")

    assert connectors["connectors"] == [{"id": "connector/1"}]
    assert logs["source"] == "connector_status"
    assert {"type": "task", "detail": {"message": "fix schema"}} in logs["logs"]
    assert {"type": "warning", "detail": {"message": "slow sync"}} in logs["logs"]
    assert status["connector"]["status"]["setup_state"] == "connected"
    assert schema["schema"] == {"schemas": {"public": {}}}
    assert destinations["destinations"] == [{"id": "destination/1"}]
    assert destination["destination"] == {"id": "destination/1"}
    assert metadata["metadata"] == {"tables": [{"name": "orders"}]}
    assert volume["data_volume"] == {"rows_synced": 42}
    assert {"type": "failed_at", "detail": "2026-05-11T00:00:00Z"} in history["sync_history"]
    assert ("GET", "https://api.fivetran.com/v1/connectors/connector%2F1", {}) in seen
    assert ("GET", "https://api.fivetran.com/v1/connectors/connector%2F1/schemas", {}) in seen
    assert ("GET", "https://api.fivetran.com/v1/destinations/destination%2F1", {}) in seen


@respx.mock
@pytest.mark.asyncio
async def test_fivetran_operational_writes_use_expected_paths_and_payloads(
    fivetran_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if request.url.path.endswith("/force"):
            return httpx.Response(200, json={"code": "Success"})
        if request.url.path.endswith("/schemas") and request.method == "PATCH":
            return httpx.Response(200, json={"data": body})
        if request.method == "PATCH":
            return httpx.Response(200, json={"data": {"id": "connector/1", "paused": body["paused"]}})
        if request.url.path.endswith("/resync"):
            return httpx.Response(200, json={"code": "Success"})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"https://api\.fivetran\.com/.*").mock(side_effect=handler)
    session = fivetran_session

    triggered = await _fivetran_tool(session, "write_trigger_sync", {"connector_id": "connector/1"}, "agent-1")
    paused = await _fivetran_tool(session, "write_pause_connector", {"connector_id": "connector/1"}, "agent-1")
    resumed = await _fivetran_tool(session, "write_resume_connector", {"connector_id": "connector/1"}, "agent-1")
    resync = await _fivetran_tool(
        session,
        "write_resync_table",
        {"connector_id": "connector/1", "schema": "public", "table": "orders"},
        "agent-1",
    )
    schema = await _fivetran_tool(
        session,
        "write_modify_connector_schema",
        {"connector_id": "connector/1", "config": {"schemas": {"public": {"enabled": True}}}},
        "agent-1",
    )
    deleted = await _fivetran_tool(session, "write_delete_connector", {"connector_id": "connector/1"}, "agent-1")

    assert triggered["status"] == "triggered"
    assert paused["result"]["data"]["paused"] is True
    assert resumed["result"]["data"]["paused"] is False
    assert resync["status"] == "triggered"
    assert schema["schema"]["data"] == {"schemas": {"public": {"enabled": True}}}
    assert deleted["status"] == "deleted"
    assert ("POST", "https://api.fivetran.com/v1/connectors/connector%2F1/force", {}) in seen
    assert ("PATCH", "https://api.fivetran.com/v1/connectors/connector%2F1", {"paused": True}) in seen
    assert ("PATCH", "https://api.fivetran.com/v1/connectors/connector%2F1", {"paused": False}) in seen
    assert ("DELETE", "https://api.fivetran.com/v1/connectors/connector%2F1", {}) in seen
