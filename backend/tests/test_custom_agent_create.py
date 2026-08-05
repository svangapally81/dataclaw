from __future__ import annotations

import importlib
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models.domain import Agent, AgentMcpGrant, Connector


@pytest.fixture(scope="module")
async def app_client(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("custom-agent-app")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}"
    os.environ["DEMO_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path/'demo.sqlite'}"
    os.environ["DEMO_MODE"] = "true"
    os.environ["MASTER_KEY"] = "test-master-key-please-change"
    os.environ["SESSION_SECRET"] = "test-session-secret-please-change"
    os.environ["DATACLAW_VECTOR_TEST_DOUBLE"] = "true"
    os.environ["DATACLAW_TEST_AUTO_CREATE_SCHEMA"] = "true"
    os.environ["DATACLAW_BCRYPT_ROUNDS"] = "4"

    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.db.session as session_module

    importlib.reload(session_module)
    from app import main as main_module

    importlib.reload(main_module)
    transport = ASGITransport(app=main_module.app)
    async with main_module.app.router.lifespan_context(main_module.app):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            login = await ac.post(
                "/auth/login",
                json={"email": "admin@dataclaw.local", "password": "dataclaw-local-admin"},
            )
            assert login.status_code == 200
            yield ac


@pytest.mark.asyncio
async def test_create_custom_background_agent_with_target_and_grants(app_client: AsyncClient) -> None:
    connectors_response = await app_client.get("/connectors")
    connectors_response.raise_for_status()
    sqlite_connector = next(item for item in connectors_response.json() if item["slug"] == "sqlite")

    created = await app_client.post(
        "/agents",
        json={
            "name": "refund_watch",
            "display_name": "Refund Watch",
            "kind": "background",
            "system_prompt": "Alert on refund spikes.",
            "sql_query": "select 1 as refund_count",
            "cadence_minutes": 10,
            "thresholds": {"rows_gt": 0},
            "uses_llm_filter": True,
            "target_connector_id": sqlite_connector["id"],
            "grants": [{"connector_slug": "sqlite", "read_enabled": True, "write_enabled": False}],
        },
    )
    created.raise_for_status()
    payload = created.json()

    assert payload["kind"] == "background"
    assert payload["sql_query"] == "select 1 as refund_count"
    assert payload["cadence_minutes"] == 10
    assert payload["thresholds"] == {"rows_gt": 0}
    assert payload["uses_llm_filter"] is True
    assert payload["target_connector_id"] == sqlite_connector["id"]

    grants = await app_client.get(f"/agents/{payload['id']}/grants")
    grants.raise_for_status()
    assert any(grant["connector_slug"] == "sqlite" and grant["read_enabled"] for grant in grants.json())


@pytest.mark.asyncio
async def test_custom_background_agent_min_cadence_guardrail(app_client: AsyncClient) -> None:
    response = await app_client.post(
        "/agents",
        json={
            "name": "too_fast",
            "display_name": "Too Fast",
            "kind": "background",
            "cadence_minutes": 1,
        },
    )
    assert response.status_code == 422
    assert "cadence_minutes must be at least 5" in response.text


@pytest.mark.asyncio
async def test_force_run_requested_when_background_agent_enabled(app_client: AsyncClient) -> None:
    background = await app_client.get("/agents?kind=background")
    background.raise_for_status()
    agent = next(item for item in background.json() if item["name"] == "freshness")

    disabled = await app_client.patch(f"/agents/{agent['id']}", json={"enabled": False})
    disabled.raise_for_status()
    enabled = await app_client.patch(f"/agents/{agent['id']}", json={"enabled": True})
    enabled.raise_for_status()

    import app.db.session as session_module
    from app.models.domain import Agent

    async with session_module.SessionLocal() as session:
        row = await session.get(Agent, agent["id"])
        assert row is not None
        assert row.force_run_requested_at is not None


@pytest.mark.asyncio
async def test_auto_grant_on_connector_test_grants_chat_write(app_client: AsyncClient) -> None:
    # v0.1.1: chat agent gets write_enabled=True on configured connectors
    # because writes are still approval-gated server-side. This removes a
    # hidden manual grant step testers had to do for Scenario 5 (Notion writes).
    import app.db.session as session_module

    async with session_module.SessionLocal() as session:
        chat_agent_row = await session.scalar(select(Agent).where(Agent.name == "chat"))
        assert chat_agent_row is not None
        sqlite_connector = await session.scalar(select(Connector).where(Connector.slug == "sqlite"))
        assert sqlite_connector is not None
        sqlite_connector.credential_state = "not_configured"
        sqlite_connector.encrypted_credentials = None
        sqlite_connector.status = "not_configured"
        grant = await session.scalar(
            select(AgentMcpGrant).where(
                AgentMcpGrant.agent_id == chat_agent_row.id,
                AgentMcpGrant.connector_slug == "sqlite",
            )
        )
        assert grant is not None
        grant.read_enabled = False
        grant.write_enabled = False
        await session.commit()

    agents = (await app_client.get("/agents")).json()
    chat_agent = next(agent for agent in agents if agent["name"] == "chat")
    grants_before = (await app_client.get(f"/agents/{chat_agent['id']}/grants")).json()
    sqlite_before = next(grant for grant in grants_before if grant["connector_slug"] == "sqlite")
    assert sqlite_before["read_enabled"] is False
    assert sqlite_before["write_enabled"] is False

    response = await app_client.post("/connectors/sqlite/test", json={"credentials": {}})
    response.raise_for_status()

    grants_after = (await app_client.get(f"/agents/{chat_agent['id']}/grants")).json()
    sqlite_after = next(grant for grant in grants_after if grant["connector_slug"] == "sqlite")
    assert sqlite_after["read_enabled"] is True
    assert sqlite_after["write_enabled"] is True


@pytest.mark.asyncio
async def test_background_run_due_endpoint_creates_custom_alert_with_fingerprint(app_client: AsyncClient) -> None:
    background = await app_client.get("/agents?kind=background")
    background.raise_for_status()
    for agent in background.json():
        disabled = await app_client.patch(f"/agents/{agent['id']}", json={"enabled": False})
        disabled.raise_for_status()

    connectors_response = await app_client.get("/connectors")
    connectors_response.raise_for_status()
    sqlite_connector = next(item for item in connectors_response.json() if item["slug"] == "sqlite")

    created = await app_client.post(
        "/agents",
        json={
            "name": "run_due_refund_watch",
            "display_name": "Run Due Refund Watch",
            "kind": "background",
            "sql_query": "select 1 as refund_count",
            "cadence_minutes": 10,
            "thresholds": {"rows_gt": 0},
            "target_connector_id": sqlite_connector["id"],
            "grants": [{"connector_slug": "sqlite", "read_enabled": True, "write_enabled": False}],
        },
    )
    created.raise_for_status()
    agent = created.json()

    run_due = await app_client.post("/agents/background/run-due")
    run_due.raise_for_status()
    payload = run_due.json()
    assert payload["count"] == 1
    assert payload["results"][0]["agent_name"] == "Run Due Refund Watch"
    assert "alert created" in payload["results"][0]["summary"]

    events = await app_client.get("/observability/events", params={"kind": "alert", "q": "Run Due Refund Watch"})
    events.raise_for_status()
    alerts = events.json()["events"]
    assert len(alerts) == 1
    assert alerts[0]["fingerprint"].startswith(f"custom:{agent['id']}:")


@pytest.mark.asyncio
async def test_legacy_monitoring_config_write_updates_unified_grant_only(app_client: AsyncClient) -> None:
    connectors_response = await app_client.get("/connectors")
    connectors_response.raise_for_status()
    airflow_connector = next(item for item in connectors_response.json() if item["slug"] == "airflow")

    updated = await app_client.put(
        "/monitoring/configs",
        json={
            "agent_name": "airflow_failure_agent",
            "connector_id": airflow_connector["id"],
            "enabled": True,
            "thresholds": {"max_failures": 1},
        },
    )
    updated.raise_for_status()
    payload = updated.json()
    assert payload["id"].startswith("unified:")
    assert payload["enabled"] is True
    assert payload["thresholds"] == {"max_failures": 1}

    import app.db.session as session_module
    from app.models.domain import Agent, AgentMcpGrant, MonitoringConfig

    async with session_module.SessionLocal() as session:
        rows = (await session.scalars(select(MonitoringConfig))).all()
        assert rows == []
        alerting = await session.scalar(select(Agent).where(Agent.name == "alerting"))
        assert alerting is not None
        grant = await session.scalar(
            select(AgentMcpGrant).where(
                AgentMcpGrant.agent_id == alerting.id,
                AgentMcpGrant.connector_slug == "airflow",
            )
        )
        assert grant is not None
        assert grant.read_enabled is True


@pytest.mark.asyncio
async def test_ollama_test_connection_reports_missing_model(app_client: AsyncClient, monkeypatch) -> None:
    import app.main as main_module

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"id": "qwen2.5:7b"}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            assert url == "http://127.0.0.1:11434/v1/models"
            return FakeResponse()

    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeAsyncClient)

    response = await app_client.post(
        "/llm/providers/ollama/test",
        json={"values": {"base_url": "http://127.0.0.1:11434/v1", "model": "llama3.1:8b"}},
    )

    response.raise_for_status()
    assert response.json() == {
        "status": "error",
        "message": "Model 'llama3.1:8b' not pulled. Run: ollama pull llama3.1:8b",
    }


@pytest.mark.asyncio
async def test_ollama_test_connection_reports_unreachable(app_client: AsyncClient, monkeypatch) -> None:
    import app.main as main_module

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url: str):
            raise main_module.httpx.ConnectError("connection refused")

    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeAsyncClient)

    response = await app_client.post(
        "/llm/providers/ollama/test",
        json={"values": {"base_url": "http://127.0.0.1:11434/v1", "model": "llama3.1:8b"}},
    )

    response.raise_for_status()
    assert response.json() == {
        "status": "error",
        "message": "Ollama not reachable at http://127.0.0.1:11434/v1",
    }
