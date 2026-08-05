"""v0 release-gate E2E suite.

These tests are intentionally gated behind ``--runslow`` plus a running DataClaw
API so default CI cannot silently replace the release gate with mocks.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import uuid

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.e2e, pytest.mark.runslow]
LIVE_LLM_STATUSES = {"no_tool_call", "completed", "mcp_tool_completed"}
LEGACY_RUNBOOK_CHAT_STATUSES = LIVE_LLM_STATUSES | {"mcp_tool_error"}


def _api_url() -> str:
    value = os.getenv("DATACLAW_API_URL")
    if not value:
        pytest.skip("DATACLAW_API_URL must point at the running v0 release candidate.")
    return value.rstrip("/")


async def _login(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/login",
        json={
            "email": os.getenv("DATACLAW_E2E_EMAIL", "e2e@dataclaw.local"),
            "password": os.getenv("DATACLAW_E2E_PASSWORD", "e2e-only-test"),
        },
    )
    response.raise_for_status()


async def _connect_airflow(client: AsyncClient, *, sync: bool) -> None:
    credentials = {
        "base_url": os.getenv("DATACLAW_E2E_AIRFLOW_URL", "http://localhost:18080"),
        "username": os.getenv("DATACLAW_E2E_AIRFLOW_USER", "admin"),
        "password": os.getenv("DATACLAW_E2E_AIRFLOW_PASSWORD", "admin"),
    }
    test_response = await client.post(
        "/connectors/airflow/test",
        json={"credentials": credentials, "persist_on_success": True},
    )
    assert test_response.status_code == 200, test_response.text
    assert test_response.json()["status"] == "ok"
    if sync:
        sync_response = await client.post("/connectors/airflow/sync")
        assert sync_response.status_code == 200, sync_response.text


async def _wait_for_airflow_dag(client: AsyncClient, dag_id: str) -> None:
    for _ in range(60):
        response = await client.get(f"/api/v1/dags/{dag_id}")
        if response.status_code == 200:
            return
        await asyncio.sleep(2)
    pytest.fail(f"Airflow DAG {dag_id!r} was not available.")


async def _seed_failed_airflow_run() -> str:
    dag_id = os.getenv("DATACLAW_E2E_FAILED_AIRFLOW_DAG", "dataclaw_e2e_failure")
    run_id = f"dataclaw_e2e__{uuid.uuid4().hex}"
    async with AsyncClient(
        base_url=os.getenv("DATACLAW_E2E_AIRFLOW_URL", "http://localhost:18080"),
        auth=(
            os.getenv("DATACLAW_E2E_AIRFLOW_USER", "admin"),
            os.getenv("DATACLAW_E2E_AIRFLOW_PASSWORD", "admin"),
        ),
        timeout=60,
    ) as airflow:
        await _wait_for_airflow_dag(airflow, dag_id)
        trigger = await airflow.post(
            f"/api/v1/dags/{dag_id}/dagRuns",
            json={"dag_run_id": run_id, "conf": {"source": "dataclaw-v0-e2e"}},
        )
        trigger.raise_for_status()
        state = await airflow.patch(f"/api/v1/dags/{dag_id}/dagRuns/{run_id}", json={"state": "failed"})
        if state.status_code in {404, 405}:
            for _ in range(90):
                state = await airflow.get(f"/api/v1/dags/{dag_id}/dagRuns/{run_id}")
                state.raise_for_status()
                payload = state.json()
                if payload.get("state") == "failed":
                    return dag_id
                await asyncio.sleep(2)
            pytest.fail(f"Airflow DAG run {dag_id}/{run_id} did not fail.")
        state.raise_for_status()
        assert state.json().get("state") == "failed"
        return dag_id


async def _run_due_background_agents(client: AsyncClient) -> dict:
    response = await client.post("/agents/background/run-due")
    response.raise_for_status()
    return response.json()


@pytest.mark.asyncio
async def test_01_boot_guards_reject_missing_master_key(monkeypatch) -> None:
    monkeypatch.setenv("MASTER_KEY", "")
    monkeypatch.setenv("SESSION_SECRET", "strong-session-secret-32bytes-1234567890")
    monkeypatch.setenv("DEMO_MODE", "false")

    config = importlib.reload(importlib.import_module("app.core.config"))
    security = importlib.reload(importlib.import_module("app.core.security"))

    with pytest.raises((RuntimeError, ValueError)):
        security.validate_runtime_secrets(
            config.get_settings().master_key,
            config.get_settings().session_secret,
        )


@pytest.mark.asyncio
async def test_02_bootstrap_admin_can_login() -> None:
    async with AsyncClient(base_url=_api_url(), timeout=60) as client:
        await _login(client)


@pytest.mark.asyncio
async def test_03_connector_sweep_and_catalog_contract() -> None:
    credentials = {
        "sqlite": {},
        "postgres": {
            "database_url": os.getenv(
                "DATACLAW_E2E_POSTGRES_URL",
                "postgresql+psycopg://dataclaw:dataclaw@localhost:15432/dataclaw_integration",
            )
        },
        "mysql": {
            "host": os.getenv("DATACLAW_E2E_MYSQL_HOST", "127.0.0.1"),
            "port": os.getenv("DATACLAW_E2E_MYSQL_PORT", "13306"),
            "database": os.getenv("DATACLAW_E2E_MYSQL_DATABASE", "dataclaw_integration"),
            "user": os.getenv("DATACLAW_E2E_MYSQL_USER", "dataclaw"),
            "password": os.getenv("DATACLAW_E2E_MYSQL_PASSWORD", "dataclaw"),
        },
        "airflow": {
            "base_url": os.getenv("DATACLAW_E2E_AIRFLOW_URL", "http://localhost:18080"),
            "username": os.getenv("DATACLAW_E2E_AIRFLOW_USER", "admin"),
            "password": os.getenv("DATACLAW_E2E_AIRFLOW_PASSWORD", "admin"),
        },
        "github": {
            "base_url": os.getenv("DATACLAW_E2E_GITHUB_URL", "http://localhost:18084"),
            "token": os.getenv("DATACLAW_E2E_GITHUB_TOKEN", "github-token"),
            "repositories": os.getenv("DATACLAW_E2E_GITHUB_REPOSITORIES", "dataclaw/analytics"),
        },
    }
    async with AsyncClient(base_url=_api_url(), timeout=120) as client:
        await _login(client)
        catalog_response = await client.get("/connectors/catalog")
        catalog_response.raise_for_status()
        catalog = catalog_response.json()
        assert len(catalog) == 20
        assert all("local_verification" not in item for item in catalog)

        for slug, connector_credentials in credentials.items():
            test_response = await client.post(
                f"/connectors/{slug}/test",
                json={"credentials": connector_credentials, "persist_on_success": True},
            )
            assert test_response.status_code == 200, test_response.text
            assert test_response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_04_ui_configured_openai_is_the_only_chat_source() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY is required for the real OpenAI portion of the v0 gate.")

    async with AsyncClient(base_url=_api_url(), timeout=180) as client:
        await _login(client)
        cleared = await client.put("/llm/providers/openai", json={"values": {"api_key": None}})
        cleared.raise_for_status()
        fallback = await client.post("/ide/chat", json={"question": "Say exactly: fallback check"})
        fallback.raise_for_status()
        assert fallback.json().get("provider") != "openai"

        configured = await client.put(
            "/llm/providers/openai",
            json={"values": {"api_key": api_key, "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini")}},
        )
        configured.raise_for_status()
        live = await client.post("/ide/chat", json={"question": "Reply with the word configured."})
        live.raise_for_status()
        assert live.json().get("provider") == "openai"
        assert live.json().get("llm_status") in LIVE_LLM_STATUSES


@pytest.mark.asyncio
async def test_05_wiki_compile_graph_contains_dags() -> None:
    async with AsyncClient(base_url=_api_url(), timeout=300) as client:
        await _login(client)
        await _connect_airflow(client, sync=True)
        compile_response = await client.post("/knowledge/compile")
        compile_response.raise_for_status()
        graph_response = await client.get("/knowledge/graph?depth=3")
        graph_response.raise_for_status()
        graph = graph_response.json()
        assert len(graph["nodes"]) >= 30
        assert len(graph["edges"]) >= 20
        assert "dag" in {node["type"] for node in graph["nodes"]}


@pytest.mark.asyncio
async def test_06_monitoring_agent_e2e_alert_exists() -> None:
    async with AsyncClient(base_url=_api_url(), timeout=240) as client:
        await _login(client)
        await _connect_airflow(client, sync=False)
        background_response = await client.get("/agents?kind=background")
        background_response.raise_for_status()
        background_agents = {agent["name"]: agent for agent in background_response.json()}
        for name, agent in background_agents.items():
            if name != "alerting":
                disable_response = await client.patch(f"/agents/{agent['id']}", json={"enabled": False})
                disable_response.raise_for_status()
        alerting = background_agents["alerting"]
        patch_response = await client.patch(
            f"/agents/{alerting['id']}",
            json={"enabled": True, "cadence_minutes": 5, "uses_llm_filter": False},
        )
        patch_response.raise_for_status()
        failed_dag_id = await _seed_failed_airflow_run()
        await _run_due_background_agents(client)
        response = await client.get("/observability/events?kind=alert&severity=critical&q=airflow")
        response.raise_for_status()
        payload = response.json()
        assert any(
            event["kind"] == "alert"
            and event.get("fingerprint", "").startswith("airflow_failure:")
            and failed_dag_id in str(event)
            for event in payload["events"]
        )


@pytest.mark.asyncio
async def test_07_observability_mock_payload_shape() -> None:
    async with AsyncClient(base_url=_api_url(), timeout=60) as client:
        await _login(client)
        response = await client.get("/observability/events")
        response.raise_for_status()
        payload = response.json()
        if os.getenv("OBSERVABILITY_MOCK", "").lower() in {"1", "true", "yes"}:
            assert payload["total"] == 6
            assert len(payload["events"]) == 6
        else:
            assert "events" in payload


@pytest.mark.asyncio
async def test_08_real_openai_chat_runbook_prompts() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for the real OpenAI portion of the v0 gate.")
    prompts = [
        "Tell me about the orders table.",
        "What does the data glossary say about LTV?",
        "What pipelines produce or consume the orders table?",
        "How many orders did we get last week?",
        "Show me revenue by month as a chart.",
        "Summarize the latest critical observability alert.",
    ]
    async with AsyncClient(base_url=_api_url(), timeout=180) as client:
        await _login(client)
        for prompt in prompts:
            response = await client.post("/ide/chat", json={"question": prompt})
            response.raise_for_status()
            payload = response.json()
            assert payload["answer"]
            assert payload.get("provider") == "openai"
            assert payload.get("llm_status") in LEGACY_RUNBOOK_CHAT_STATUSES
