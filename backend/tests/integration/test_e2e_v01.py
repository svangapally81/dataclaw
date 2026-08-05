"""v0.1 release-gate E2E suite.

Requires a running DataClaw API plus real Postgres, Notion, and Airflow
connectors. The suite is gated behind ``--runslow`` so default CI cannot
silently replace this with mocks.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.e2e, pytest.mark.runslow]
LIVE_LLM_STATUSES = {"no_tool_call", "completed", "mcp_tool_completed"}


def _api_url() -> str:
    value = os.getenv("DATACLAW_API_URL")
    if not value:
        pytest.skip("DATACLAW_API_URL must point at the running v0.1 release candidate.")
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


def _required_credentials() -> dict[str, dict]:
    notion_token = os.getenv("NOTION_TOKEN") or os.getenv("NOTION_INTEGRATION_TOKEN")
    credentials = {
        "postgres": {
            "database_url": os.getenv(
                "DATACLAW_E2E_POSTGRES_URL",
                "postgresql+psycopg://dataclaw:dataclaw@localhost:15432/dataclaw_integration",
            )
        },
        "airflow": {
            "base_url": os.getenv("DATACLAW_E2E_AIRFLOW_URL", "http://localhost:18080"),
            "username": os.getenv("DATACLAW_E2E_AIRFLOW_USER", "admin"),
            "password": os.getenv("DATACLAW_E2E_AIRFLOW_PASSWORD", "admin"),
        },
    }
    if notion_token:
        credentials["notion"] = {
            "integration_token": notion_token,
            "base_url": os.getenv("DATACLAW_E2E_NOTION_URL", "https://api.notion.com"),
        }
    return credentials


async def _connect_required_sources(
    client: AsyncClient,
    *,
    slugs: set[str] | None = None,
    sync: bool,
) -> dict[str, dict]:
    credentials = _required_credentials()
    if slugs is None and "notion" not in credentials:
        pytest.skip("NOTION_TOKEN or NOTION_INTEGRATION_TOKEN is required for the v0.1 release gate.")
    selected = credentials if slugs is None else {slug: credentials[slug] for slug in slugs}
    for slug, values in selected.items():
        test_response = await client.post(
            f"/connectors/{slug}/test",
            json={"credentials": values, "persist_on_success": True},
        )
        assert test_response.status_code == 200, test_response.text
        assert test_response.json()["status"] == "ok"
        if sync:
            sync_response = await client.post(f"/connectors/{slug}/sync")
            assert sync_response.status_code == 200, sync_response.text
    response = await client.get("/connectors")
    response.raise_for_status()
    by_slug = {item["slug"]: item for item in response.json()}
    for slug in selected:
        assert by_slug[slug]["credential_state"] == "configured"
    return by_slug


async def _connect_and_sync_required_sources(client: AsyncClient) -> dict[str, dict]:
    return await _connect_required_sources(client, sync=True)


async def _configure_provider(client: AsyncClient) -> str:
    provider = os.getenv("DATACLAW_LLM_PROVIDER", "openai")
    if provider == "ollama":
        response = await client.put(
            "/llm/providers/ollama",
            json={
                "values": {
                    "base_url": os.getenv("DATACLAW_E2E_OLLAMA_URL", "http://localhost:11434/v1"),
                    "model": os.getenv("DATACLAW_E2E_OLLAMA_MODEL", "llama3.1:8b"),
                    "embedding_model": os.getenv("DATACLAW_E2E_OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
                }
            },
        )
        response.raise_for_status()
        return "ollama"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY is required when DATACLAW_LLM_PROVIDER is openai.")
    response = await client.put(
        "/llm/providers/openai",
        json={"values": {"api_key": api_key, "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini")}},
    )
    response.raise_for_status()
    return "openai"


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
            json={"dag_run_id": run_id, "conf": {"source": "dataclaw-v01-e2e"}},
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


async def _events(client: AsyncClient, *, kind: str, q: str | None = None) -> list[dict]:
    response = await client.get("/observability/events", params={"kind": kind, "q": q, "limit": 200})
    response.raise_for_status()
    return response.json()["events"]


async def _run_due_background_agents(client: AsyncClient, *, now: datetime | None = None) -> dict:
    params = {"now": now.isoformat()} if now else None
    response = await client.post("/agents/background/run-due", params=params)
    response.raise_for_status()
    return response.json()


@pytest.mark.asyncio
async def test_01_sources_compile_and_chat_with_selected_provider() -> None:
    async with AsyncClient(base_url=_api_url(), timeout=1800) as client:
        await _login(client)
        await _connect_and_sync_required_sources(client)
        provider = await _configure_provider(client)

        compile_response = await client.post("/knowledge/compile")
        compile_response.raise_for_status()
        graph_response = await client.get("/knowledge/graph?depth=3")
        graph_response.raise_for_status()
        graph = graph_response.json()
        assert graph["nodes"]

        prompts = [
            "Summarize one Postgres table.",
            "Summarize one Notion page.",
            "Summarize the status of one Airflow DAG.",
        ]
        for prompt in prompts:
            chat_response = await client.post("/ide/chat", json={"question": prompt})
            chat_response.raise_for_status()
            payload = chat_response.json()
            assert payload["answer"]
            if provider == "ollama":
                assert payload.get("provider") == "ollama"
                assert payload.get("llm_status") in LIVE_LLM_STATUSES
            else:
                assert payload.get("provider") == "openai"
                assert payload.get("llm_status") in LIVE_LLM_STATUSES


@pytest.mark.asyncio
async def test_02_background_dispatch_custom_agent_cadence_and_grant_gating() -> None:
    async with AsyncClient(base_url=_api_url(), timeout=240) as client:
        await _login(client)
        connectors = await _connect_required_sources(client, slugs={"postgres", "airflow"}, sync=False)

        background_response = await client.get("/agents?kind=background")
        background_response.raise_for_status()
        background_agents = {agent["name"]: agent for agent in background_response.json()}
        assert {"alerting", "data_quality", "freshness", "ingestion", "reconciler"}.issubset(background_agents)
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
        assert patch_response.json()["uses_llm_filter"] is False

        failed_dag_id = await _seed_failed_airflow_run()
        await _run_due_background_agents(client)
        airflow_alerts = await _events(client, kind="alert", q=failed_dag_id)
        assert any(
            event["kind"] == "alert"
            and event["fingerprint"]
            and event["fingerprint"].startswith("airflow_failure:")
            for event in airflow_alerts
        )

        postgres = connectors["postgres"]
        custom_name = f"refund_volume_watch_{uuid.uuid4().hex[:10]}"
        custom_display = f"Refund Volume Watch {custom_name[-10:]}"
        custom_response = await client.post(
            "/agents",
            json={
                "name": custom_name,
                "display_name": custom_display,
                "kind": "background",
                "sql_query": "select 1 as refund_count",
                "cadence_minutes": 10,
                "thresholds": {"rows_gt": 0},
                "target_connector_id": postgres["id"],
                "grants": [{"connector_slug": "postgres", "read_enabled": True, "write_enabled": False}],
            },
        )
        custom_response.raise_for_status()
        custom = custom_response.json()

        grants_response = await client.get(f"/agents/{custom['id']}/grants")
        grants_response.raise_for_status()
        assert any(grant["connector_slug"] == "postgres" and grant["read_enabled"] for grant in grants_response.json())

        now = datetime.now(UTC)
        first_tick = await _run_due_background_agents(client, now=now)
        assert any(result.get("agent_name") == custom_display for result in first_tick["results"])
        custom_alerts = await _events(client, kind="alert", q=custom_display)
        assert any(
            event["fingerprint"] and event["fingerprint"].startswith(f"custom:{custom['id']}:")
            for event in custom_alerts
        )

        five_minute_tick = await _run_due_background_agents(client, now=now + timedelta(minutes=5))
        assert all(result.get("agent_name") != custom_display for result in five_minute_tick["results"])
        ten_minute_tick = await _run_due_background_agents(client, now=now + timedelta(minutes=11))
        assert any(result.get("agent_name") == custom_display for result in ten_minute_tick["results"])

        no_grant_name = f"no_grant_watch_{uuid.uuid4().hex[:10]}"
        no_grant_display = f"No Grant Watch {no_grant_name[-10:]}"
        no_grant_response = await client.post(
            "/agents",
            json={
                "name": no_grant_name,
                "display_name": no_grant_display,
                "kind": "background",
                "sql_query": "select 1 as blocked",
                "cadence_minutes": 5,
                "thresholds": {"rows_gt": 0},
                "target_connector_id": postgres["id"],
                "grants": [{"connector_slug": "postgres", "read_enabled": False, "write_enabled": False}],
            },
        )
        no_grant_response.raise_for_status()
        no_grant_tick = await _run_due_background_agents(client, now=now + timedelta(minutes=20))
        no_grant_result = next(result for result in no_grant_tick["results"] if result.get("agent_name") == no_grant_display)
        assert no_grant_result["status"] == "skipped"
        assert "no read grant" in no_grant_result["summary"]
