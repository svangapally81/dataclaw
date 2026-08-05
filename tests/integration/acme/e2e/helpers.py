from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.integration.acme.common import load_acme_ids
from tests.integration.acme.seed.saas.common import (
    ACME_DOCS,
    DEFAULT_SNOWFLAKE_WAREHOUSE,
    SAAS_ENV,
    EnvRequirement,
    env_first,
    github_test_repo,
    normalize_snowflake_account,
    parse_redshift_endpoint,
    redshift_cluster_identifier,
)

CONNECTOR_ENV = {
    **SAAS_ENV,
    "openai": ["OPENAI_API_KEY"],
    "postgres": [],
    "mysql": [],
    "sql_server": [],
    "trino": [],
    "airflow": [],
    "dbt": [],
    "prefect": [],
    "dagster": [],
    "airbyte": [],
    "sqlite": [],
}


def require_connectors(*slugs: str) -> None:
    missing: dict[str, list[str]] = {}
    for slug in slugs:
        names = CONNECTOR_ENV.get(slug, [])
        absent = _missing_requirements(names)
        if absent:
            missing[slug] = absent
    if missing:
        detail = "; ".join(f"{slug}: {', '.join(names)}" for slug, names in missing.items())
        pytest.skip(f"no creds for Acme connector(s): {detail}")


def credentials_for(slug: str) -> dict[str, Any]:
    if slug == "notion":
        return {"integration_token": env_first("NOTION_INTEGRATION_TOKEN", "NOTION_TOKEN"), "database_ids": os.getenv("NOTION_TEST_DATABASE_IDS", "")}
    if slug == "github":
        return {
            "token": env_first("GITHUB_TEST_TOKEN", "GH_TEST_TOKEN"),
            "repositories": _manifest_value("saas", "github", "repo") or github_test_repo(),
        }
    if slug == "confluence":
        return {
            "site_url": os.getenv("CONFLUENCE_SITE_URL"),
            "email": os.getenv("CONFLUENCE_EMAIL"),
            "api_token": env_first("CONFLUENCE_API_TOKEN", "CONFLUENCE_API_BASIC_AUTH_TOKEN", "CONFLUENCE_API_OAUTH_TOKEN"),
        }
    if slug == "bigquery":
        return {"service_account_json": os.getenv("BIGQUERY_SERVICE_ACCOUNT_JSON"), "project_id": os.getenv("BIGQUERY_PROJECT_ID"), "dataset": "acme_analytics"}
    if slug == "snowflake":
        return {
            "account": normalize_snowflake_account(os.getenv("SNOWFLAKE_ACCOUNT") or ""),
            "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE")
            or _manifest_value("saas", "snowflake", "warehouse")
            or DEFAULT_SNOWFLAKE_WAREHOUSE,
            "database": os.getenv("SNOWFLAKE_DATABASE") or "ACME",
            "schema": os.getenv("SNOWFLAKE_SCHEMA") or "MARTS",
            "user": os.getenv("SNOWFLAKE_USER"),
            "password": os.getenv("SNOWFLAKE_PASSWORD"),
            "private_key": os.getenv("SNOWFLAKE_PRIVATE_KEY"),
            "private_key_passphrase": os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"),
        }
    if slug == "databricks":
        return {
            "workspace_url": env_first("DATABRICKS_WORKSPACE_URL", "DATABRICKS_HOST"),
            "http_path": os.getenv("DATABRICKS_HTTP_PATH"),
            "token": os.getenv("DATABRICKS_TOKEN"),
        }
    if slug == "redshift":
        endpoint = env_first("REDSHIFT_CLUSTER_ENDPOINT", "REDSHIFT_ENDPOINT")
        endpoint_db = parse_redshift_endpoint(endpoint)[2] if endpoint else None
        return {
            "cluster_endpoint": endpoint,
            "database": os.getenv("REDSHIFT_DATABASE") or endpoint_db or "dev",
            "user": os.getenv("REDSHIFT_USER"),
            "password": os.getenv("REDSHIFT_PASSWORD"),
            "cluster_identifier": os.getenv("REDSHIFT_CLUSTER_IDENTIFIER")
            or (redshift_cluster_identifier(endpoint) if endpoint else None),
        }
    if slug == "fivetran":
        return {"api_key": os.getenv("FIVETRAN_API_KEY"), "api_secret": os.getenv("FIVETRAN_API_SECRET")}
    if slug == "postgres":
        return {"database_url": "postgresql+psycopg://dataclaw:dataclaw@127.0.0.1:15432/dataclaw_integration"}
    if slug == "mysql":
        return {"host": "127.0.0.1", "port": 13306, "database": "dataclaw_integration", "user": "dataclaw", "password": "dataclaw"}
    if slug == "sql_server":
        return {"host": "127.0.0.1", "port": 11433, "database": "dataclaw_integration", "user": "sa", "password": "DataClaw!Passw0rd"}
    if slug == "trino":
        return {"host": "127.0.0.1", "port": 18088, "catalog": "memory", "schema": "default", "user": "dataclaw"}
    if slug == "airflow":
        return {"base_url": "http://127.0.0.1:18080", "username": "admin", "password": "admin"}
    if slug == "dbt":
        return {"base_url": "http://127.0.0.1:18087/api/v2/accounts/1", "api_token": "fixture", "account_id": "1"}
    if slug == "prefect":
        return {"api_url": "http://127.0.0.1:18082/api", "api_key": "fixture"}
    if slug == "dagster":
        return {"graphql_url": "http://127.0.0.1:18083/graphql", "token": "fixture"}
    if slug == "airbyte":
        return {"api_url": "http://127.0.0.1:18084", "api_key": "fixture"}
    if slug == "openai":
        return {"api_key": os.getenv("OPENAI_API_KEY"), "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini")}
    return {}


def _manifest_value(*path: str) -> str | None:
    try:
        value: Any = load_acme_ids()
    except FileNotFoundError:
        return None
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return str(value) if value else None


def _missing_requirements(names: list[EnvRequirement]) -> list[str]:
    absent: list[str] = []
    for requirement in names:
        if isinstance(requirement, tuple):
            if not env_first(*requirement):
                absent.append(" or ".join(requirement))
            continue
        if not os.getenv(requirement):
            absent.append(requirement)
    return absent


async def configure_connectors(client: AsyncClient, *slugs: str, sync: bool = True) -> None:
    require_connectors(*slugs)
    for slug in slugs:
        if slug == "sqlite":
            continue
        if _fixture_backed_connector(slug):
            await _configure_fixture_connector(slug)
            continue
        response = await client.post(f"/connectors/{slug}/test", json={"credentials": credentials_for(slug), "persist_on_success": True})
        response.raise_for_status()
        payload = response.json()
        assert payload.get("status") == "ok", f"{slug} connector test failed: {payload}"
        if slug == "notion":
            await _ingest_fixture_payload(slug)
            continue
        if sync and slug not in {"openai"}:
            sync_response = await client.post(f"/connectors/{slug}/sync")
            if _sync_fixture_fallback(slug, sync_response):
                await _ingest_fixture_payload(slug)
                continue
            sync_response.raise_for_status()
        await _ingest_fixture_payload(slug)


def _fixture_backed_connector(slug: str) -> bool:
    return slug == "redshift" and _manifest_value("saas", "redshift", "connection_api") == "fixture"


def _sync_fixture_fallback(slug: str, response) -> bool:  # noqa: ANN001
    if response.status_code < 400:
        return False
    detail = response.text.lower()
    return slug == "prefect" and ("connecttimeout" in detail or "connection timeout" in detail)


async def _configure_fixture_connector(slug: str) -> None:
    from app.core.config import get_settings
    from app.core.security import encrypt_json
    from app.db.session import SessionLocal
    from app.models.domain import Agent, AgentMcpGrant, Connector, Workspace
    from app.services.connectors.catalog import CATALOG_BY_SLUG

    catalog = CATALOG_BY_SLUG[slug]
    async with SessionLocal() as session:
        workspace = await session.scalar(select(Workspace).order_by(Workspace.created_at))
        if workspace is None:
            workspace = Workspace(name="Acme Co")
            session.add(workspace)
            await session.flush()
        connector = await session.scalar(
            select(Connector).where(Connector.workspace_id == workspace.id, Connector.slug == slug)
        )
        if connector is None:
            connector = Connector(
                workspace_id=workspace.id,
                slug=slug,
                category=catalog.category.value,
                display_name=catalog.display_name,
            )
            session.add(connector)
        connector.status = "ok"
        connector.credential_state = "configured"
        connector.last_test_message = "Acme fixture-backed connector."
        connector.encrypted_credentials = encrypt_json(get_settings().master_key, credentials_for(slug))
        connector.sync_summary = {"behavior": "Acme fixture-backed connector.", "fixture": True}

        agents = (await session.scalars(select(Agent).where(Agent.workspace_id == workspace.id))).all()
        for agent in agents:
            grant = await session.scalar(
                select(AgentMcpGrant).where(
                    AgentMcpGrant.agent_id == agent.id,
                    AgentMcpGrant.connector_slug == slug,
                )
            )
            if grant is None:
                grant = AgentMcpGrant(agent_id=agent.id, connector_slug=slug)
                session.add(grant)
            grant.read_enabled = True
        await session.commit()


async def _ingest_fixture_payload(slug: str) -> None:
    payload = _fixture_ingestion_payload(slug)
    if not payload:
        return
    from app.db.session import SessionLocal
    from app.models.domain import Workspace
    from app.services.ingestion.service import IngestionService

    async with SessionLocal() as session:
        workspace = await session.scalar(select(Workspace).order_by(Workspace.created_at))
        if workspace is None:
            return
        await IngestionService(session).ingest_payload(workspace.id, slug, payload)


def _fixture_ingestion_payload(slug: str) -> dict[str, Any]:
    if slug == "notion":
        return {
            "pages": [
                {"id": f"acme-notion-{title.lower().replace(' ', '-')}", "title": title, "body": body}
                for title, body in ACME_DOCS.items()
            ]
        }
    if slug == "airflow":
        return {
            "pages": [
                {
                    "id": "acme-airflow-revenue-daily",
                    "title": "Airflow revenue_daily pipeline",
                    "body": (
                        "Airflow DAG acme_revenue_recalc updates revenue_daily after upstream "
                        "customer and order loads complete."
                    ),
                }
            ]
        }
    if slug == "prefect":
        return {
            "pages": [
                {
                    "id": "acme-prefect-revenue-recalc",
                    "title": "Prefect acme_revenue_recalc",
                    "body": (
                        "Prefect flow acme_revenue_recalc refreshes Snowflake ACME.MARTS.REVENUE_DAILY "
                        "and validates the revenue_daily output."
                    ),
                }
            ]
        }
    return {}


async def grant_chat_write(client: AsyncClient, *slugs: str) -> None:
    agents = (await client.get("/agents")).json()
    chat = next(agent for agent in agents if agent["name"] == "chat")
    grants = []
    for slug in slugs:
        grants.append({"connector_slug": slug, "read_enabled": True, "write_enabled": True if slug != "openai" else False})
    response = await client.put(f"/agents/{chat['id']}/grants", json={"grants": grants})
    response.raise_for_status()


async def chat(client: AsyncClient, question: str, *, connector_slug: str | None = None) -> dict[str, Any]:
    """Send a chat question and return the real LLM response.

    No fixture fallbacks here. If the chat agent picks unexpected tools or
    returns a weak answer, the test should fail honestly so we can
    diagnose and improve the agent — not be papered over with a synthesized
    fixture response.
    """
    payload: dict[str, Any] = {"question": question}
    if connector_slug:
        payload["connector_slug"] = connector_slug
    response = await client.post("/ide/chat", json=payload)
    response.raise_for_status()
    return response.json()


async def observed_tool_calls(client: AsyncClient) -> set[str]:
    response = await client.get("/observability/events", params={"kind": "agent_run", "limit": 100})
    response.raise_for_status()
    calls: set[str] = set()
    for event in response.json().get("events", []):
        for call in event.get("tool_calls", []):
            connector = call.get("connector_slug")
            tool = call.get("tool_name")
            if connector and tool:
                calls.add(f"{connector}.{tool}")
    return calls


async def event_ids(client: AsyncClient) -> set[str]:
    response = await client.get("/observability/events", params={"limit": 200})
    response.raise_for_status()
    return {str(event.get("id")) for event in response.json().get("events", []) if event.get("id")}


async def observed_tool_calls_since(client: AsyncClient, before_ids: set[str]) -> set[str]:
    response = await client.get("/observability/events", params={"kind": "agent_run", "limit": 100})
    response.raise_for_status()
    calls: set[str] = set()
    for event in response.json().get("events", []):
        if str(event.get("id")) in before_ids:
            continue
        for call in event.get("tool_calls", []):
            connector = call.get("connector_slug")
            tool = call.get("tool_name")
            if connector and tool:
                calls.add(f"{connector}.{tool}")
    return calls


def response_tool_calls(payload: dict[str, Any]) -> set[str]:
    calls: set[str] = set()
    raw_calls = list(payload.get("tool_calls") or [])
    if payload.get("tool_call"):
        raw_calls.append(payload["tool_call"])
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        connector = call.get("connector_slug")
        tool = call.get("tool") or call.get("tool_name")
        if connector and tool:
            calls.add(f"{connector}.{tool}")
    return calls


async def chat_tool_calls(client: AsyncClient, payload: dict[str, Any], before_ids: set[str] | None = None) -> set[str]:
    calls = response_tool_calls(payload)
    if before_ids is not None:
        calls |= await observed_tool_calls_since(client, before_ids)
    return calls


def assert_tool_called(calls: set[str], *expected: str) -> None:
    missing = [call for call in expected if call not in calls]
    assert not missing, f"missing tool calls {missing}; observed {sorted(calls)}"


def assert_tool_prefix(calls: set[str], *prefixes: str) -> None:
    missing = [prefix for prefix in prefixes if not any(call.startswith(prefix) for call in calls)]
    assert not missing, f"missing tool call prefixes {missing}; observed {sorted(calls)}"


def assert_answer_contains(payload: dict[str, Any], *needles: str) -> None:
    answer = str(payload.get("answer") or "").lower()
    missing = [needle for needle in needles if needle.lower() not in answer]
    assert not missing, f"answer missing {missing}: {payload.get('answer')}"


def assert_answer_contains_any(payload: dict[str, Any], *groups: tuple[str, ...]) -> None:
    answer = str(payload.get("answer") or "").lower()
    missing = [group for group in groups if not any(needle.lower() in answer for needle in group)]
    assert not missing, f"answer missing any of {missing}: {payload.get('answer')}"


def assert_answer_matches(payload: dict[str, Any], pattern: str) -> None:
    answer = str(payload.get("answer") or "")
    assert re.search(pattern, answer, flags=re.IGNORECASE), f"answer did not match {pattern!r}: {answer}"


async def assert_no_error_events(client: AsyncClient, before_ids: set[str] | None = None) -> None:
    response = await client.get("/observability/events", params={"limit": 100})
    response.raise_for_status()
    errors = [
        event
        for event in response.json().get("events", [])
        if (before_ids is None or str(event.get("id")) not in before_ids)
        and event.get("severity") == "critical"
        and event.get("state") == "failed"
    ]
    assert not errors, errors


async def compile_workspace(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/knowledge/compile")
    response.raise_for_status()
    return response.json()


async def retrieve_sources(client: AsyncClient, question: str) -> list[str]:
    response = await client.get("/knowledge/search", params={"q": question, "layer": "all", "limit": 20})
    response.raise_for_status()
    sources = []
    for item in response.json().get("results", []):
        parts = [
            item.get("source"),
            item.get("source_type"),
            item.get("title"),
            item.get("snippet"),
            item.get("metadata"),
        ]
        sources.append(" ".join(str(part) for part in parts if part))
    return sources


async def write_runbook_disk_edit(client: AsyncClient, body: str) -> None:
    pages = (await client.get("/knowledge/pages")).json()
    runbook = next((page for page in pages if "runbook" in page.get("path", "").lower()), None)
    if runbook is None or not runbook.get("disk_path"):
        pytest.skip("Acme runbook wiki page is not available for reconciliation")
    Path(runbook["disk_path"]).write_text(body, encoding="utf-8")
