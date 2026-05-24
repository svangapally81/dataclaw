from __future__ import annotations

import json
import os
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import encrypt_json
from app.db.base import Base
from app.models.domain import Agent, AgentMcpGrant, Connector, Workspace
from app.services.connectors.adapters import seed_sqlite_demo
from app.services.connectors.catalog import CATALOG_BY_SLUG
from app.services.mcp_catalog import tools_for_slug
from app.services.mcp_executor import McpExecutionError, execute_mcp_tool
from tests.integration.acme.common import load_acme_ids
from tests.integration.acme.seed.saas.common import (
    DEFAULT_SNOWFLAKE_WAREHOUSE,
    SAAS_ENV,
    EnvRequirement,
    env_first,
    github_test_repo,
    normalize_snowflake_account,
    parse_redshift_endpoint,
    redshift_cluster_identifier,
)

from .conftest import load_fixture_matrix

pytestmark = pytest.mark.integration
os.environ.setdefault("MASTER_KEY", "test-master-key-please-change")

CONTAINER_ENDPOINTS = {
    "postgres": ("127.0.0.1", 15432),
    "mysql": ("127.0.0.1", 13306),
    "sql_server": ("127.0.0.1", 11433),
    "trino": ("127.0.0.1", 18088),
    "airflow": ("127.0.0.1", 18080),
    "dbt": ("127.0.0.1", 18087),
    "prefect": ("127.0.0.1", 18082),
    "dagster": ("127.0.0.1", 18083),
    "airbyte": ("127.0.0.1", 18084),
}

CONTAINER_CREDENTIALS = {
    "postgres": {
        "database_url": "postgresql+psycopg://dataclaw:dataclaw@127.0.0.1:15432/dataclaw_integration",
        "host": "127.0.0.1",
        "port": 15432,
        "database": "dataclaw_integration",
        "user": "dataclaw",
        "password": "dataclaw",
    },
    "mysql": {"host": "127.0.0.1", "port": 13306, "database": "dataclaw_integration", "user": "dataclaw", "password": "dataclaw"},
    "sql_server": {"host": "127.0.0.1", "port": 11433, "database": "dataclaw_integration", "user": "sa", "password": "DataClaw!Passw0rd"},
    "trino": {"host": "127.0.0.1", "port": 18088, "catalog": "memory", "schema": "default", "user": "dataclaw"},
    "airflow": {"base_url": "http://127.0.0.1:18080", "username": "admin", "password": "admin"},
    "dbt": {"base_url": "http://127.0.0.1:18087/api/v2/accounts/1", "api_token": "fixture", "account_id": "1"},
    "prefect": {"api_url": "http://127.0.0.1:18082/api", "api_key": "fixture"},
    "dagster": {
        "graphql_url": "http://127.0.0.1:18083/graphql",
        "token": "",
        "repository_name": "__repository__",
        "repository_location_name": "dagster_app.py",
    },
    "airbyte": {"api_url": "http://127.0.0.1:18084", "api_key": ""},
}
LIVE_WRITE_OK_STATUSES = {
    "cancelled",
    "created",
    "deleted",
    "executed",
    "ok",
    "paused",
    "pending_approval",
    "resumed",
    "terminated",
    "triggered",
    "updated",
}
DATABRICKS_REST_FIXTURE_TOOLS = {
    "read_get_notebook",
    "read_get_run_logs",
    "read_get_unity_asset",
    "read_list_clusters",
    "read_list_jobs",
    "read_list_warehouses",
    "write_run_notebook",
    "write_start_cluster",
    "write_stop_cluster",
    "write_trigger_job",
    "write_update_unity_grants",
}
BIGQUERY_JOB_METADATA_FIXTURE_TOOLS = {
    "read_get_query_history",
    "read_get_slot_usage",
}
DATABRICKS_SQL_FIXTURE_TOOLS = {
    "read_get_lineage",
    "read_get_query_history",
    "read_get_row_count",
    "read_get_schema",
    "read_get_table_freshness",
    "read_list_tables",
    "read_query_select",
}
FIVETRAN_PARTIAL_API_FIXTURE_TOOLS = {
    "read_get_connector_schema",
    "read_get_data_volume",
    "read_get_metadata",
}
NOTION_DATABASE_FIXTURE_TOOLS = {
    "read_get_database",
    "read_query_database",
}
NOTION_BLOCK_FIXTURE_TOOLS = {
    "read_get_block_children",
    "read_get_comments",
}

@pytest_asyncio.fixture
async def acme_sqlite_runtime(tmp_path: Path):
    app_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'app.sqlite'}")
    data_path = tmp_path / "acme.sqlite"
    seed_sqlite_demo(data_path)
    data_engine = create_async_engine(f"sqlite+aiosqlite:///{data_path}")
    SessionLocal = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        session.info["session_factory"] = SessionLocal
        workspace = Workspace(name="Acme Co")
        session.add(workspace)
        await session.flush()
        agent = Agent(
            workspace_id=workspace.id,
            name="chat",
            display_name="Chat",
            system_prompt="Use Acme MCP tools.",
            is_system=True,
        )
        session.add(agent)
        connector = Connector(
            workspace_id=workspace.id,
            slug="sqlite",
            category="data_store",
            display_name="SQLite",
            status="ok",
            credential_state="configured",
            sync_summary={"behavior": "Acme coverage SQLite fixture."},
        )
        session.add(connector)
        await session.flush()
        session.add(AgentMcpGrant(agent_id=agent.id, connector_slug="sqlite", read_enabled=True, write_enabled=True))
        await session.commit()
        yield session, data_engine, agent.id
    await data_engine.dispose()
    await app_engine.dispose()


@pytest_asyncio.fixture
async def acme_mcp_runtime(tmp_path: Path, connector_slug: str):
    app_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'app.sqlite'}")
    sqlite_data_path = tmp_path / "acme.sqlite"
    seed_sqlite_demo(sqlite_data_path)
    sqlite_data_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_data_path}")
    SessionLocal = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        session.info["session_factory"] = SessionLocal
        workspace = Workspace(name="Acme Co")
        session.add(workspace)
        await session.flush()
        agent = Agent(
            workspace_id=workspace.id,
            name="chat",
            display_name="Chat",
            system_prompt="Use Acme MCP tools.",
            is_system=True,
        )
        session.add(agent)
        credentials = _credentials_for_slug(connector_slug)
        connector = Connector(
            workspace_id=workspace.id,
            slug=connector_slug,
            category=CATALOG_BY_SLUG[connector_slug].category.value,
            display_name=CATALOG_BY_SLUG[connector_slug].display_name,
            status="ok",
            credential_state="configured" if credentials else "not_configured",
            encrypted_credentials=encrypt_json(get_settings().master_key, credentials) if credentials else None,
            sync_summary={"behavior": "Acme live MCP coverage fixture."},
        )
        session.add(connector)
        await session.flush()
        session.add(AgentMcpGrant(agent_id=agent.id, connector_slug=connector_slug, read_enabled=True, write_enabled=True))
        await session.commit()
        yield session, sqlite_data_engine, agent.id
    await sqlite_data_engine.dispose()
    await app_engine.dispose()


def test_fixtures_cover_all_catalog_tools() -> None:
    matrix = load_fixture_matrix()
    missing: list[str] = []
    extra: list[str] = []
    for slug in sorted(CATALOG_BY_SLUG):
        expected = set(tools_for_slug(slug)[0]) | set(tools_for_slug(slug)[1])
        actual = set((matrix.get(slug) or {}).keys())
        missing.extend(f"{slug}.{tool}" for tool in sorted(expected - actual))
        extra.extend(f"{slug}.{tool}" for tool in sorted(actual - expected))
    assert not missing, "Missing Acme coverage fixtures:\n" + "\n".join(missing)
    assert not extra, "Unknown Acme coverage fixtures:\n" + "\n".join(extra)


def test_confluence_fixtures_use_confluence_seed_ids() -> None:
    confluence = load_fixture_matrix()["confluence"]
    page_tools = {
        "read_get_page",
        "read_get_page_children",
        "read_get_page_history",
        "read_get_comments",
        "read_get_labels",
        "write_append_to_page",
        "write_update_page",
        "write_add_label",
        "write_create_comment",
        "write_create_attachment",
        "write_move_page",
        "write_delete_page",
    }
    for tool_name in page_tools:
        args = confluence[tool_name]["args"]
        assert args["page_id"].startswith("$ACME_CONFLUENCE_"), f"{tool_name} must use a Confluence page ID"
    assert confluence["read_get_space"]["args"] == {"space_key": "$ACME_CONFLUENCE_SPACE_KEY"}
    assert confluence["write_create_page"]["args"]["space_key"] == "$ACME_CONFLUENCE_SPACE_KEY"


@pytest.mark.asyncio
async def test_mcp_tool_has_executable_fixture(
    connector_slug: str,
    tool_name: str,
    tool_fixture: dict,
    acme_mcp_runtime,
) -> None:
    """Fast default gate: every catalog tool has executable fixture metadata.

    The live execution path is enabled explicitly with RUN_ACME_MCP_COVERAGE=1
    after seed_acme.py has configured connectors and acme_ids.json.
    """
    assert isinstance(tool_fixture.get("args"), dict)
    assert isinstance(tool_fixture.get("expect_shape"), dict)
    if os.getenv("RUN_ACME_MCP_COVERAGE") != "1":
        pytest.skip("Set RUN_ACME_MCP_COVERAGE=1 to execute live MCP coverage.")
    ready, reason = _has_creds(connector_slug)
    if not ready:
        pytest.skip(reason)

    session, engine, agent_id = acme_mcp_runtime
    arguments = _substitute_placeholders(dict(tool_fixture["args"]))
    unresolved = _unresolved_placeholders(arguments)
    if unresolved:
        pytest.skip(f"missing Acme seeded IDs for {connector_slug}.{tool_name}: {', '.join(unresolved)}")
    started = datetime.now(UTC)
    fixture_reason = _live_fixture_reason(connector_slug, tool_name)
    if fixture_reason:
        _record_live_result(
            connector_slug,
            tool_name,
            status="fixture",
            started_at=started,
            detail={"fixture": True, "reason": fixture_reason},
        )
        return
    try:
        result = await execute_mcp_tool(
            session=session,
            engine=engine,
            connector_slug=connector_slug,
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id,
            user_email="acme-rig@dataclaw.local",
            run_id="acme-coverage",
        )
    except McpExecutionError as exc:
        _record_live_result(
            connector_slug,
            tool_name,
            status="error",
            started_at=started,
            detail={"status_code": exc.status_code, "detail": exc.detail},
        )
        raise

    allowed = set(tool_fixture.get("expect_shape", {}).get("status") or ["ok"])
    if tool_name.startswith("write_"):
        allowed |= LIVE_WRITE_OK_STATUSES
    assert result.get("status") in allowed, result
    _assert_shape(result, tool_fixture.get("expect_shape") or {})
    _assert_read_tool_has_payload(tool_name, result)
    _record_live_result(
        connector_slug,
        tool_name,
        status=str(result.get("status") or "ok"),
        started_at=started,
        detail={"result_keys": sorted(result), "result_size_bytes": len(json.dumps(result, default=str).encode("utf-8"))},
    )


def _has_creds(connector_slug: str) -> tuple[bool, str]:
    if connector_slug == "sqlite":
        return True, "sqlite uses bundled Acme demo data"
    if connector_slug == "openai":
        return bool(os.getenv("OPENAI_API_KEY")), "no creds for openai: OPENAI_API_KEY"
    if connector_slug in SAAS_ENV:
        missing = _missing_requirements(SAAS_ENV[connector_slug])
        if connector_slug == "github" and "GITHUB_TEST_REPO" in missing and github_test_repo():
            missing.remove("GITHUB_TEST_REPO")
        return not missing, f"no creds for {connector_slug}: {', '.join(missing)}"
    endpoint = CONTAINER_ENDPOINTS.get(connector_slug)
    if endpoint is None:
        return False, f"no reachability check configured for {connector_slug}"
    host, port = endpoint
    try:
        with socket.create_connection((host, port), timeout=1):
            return True, f"{connector_slug} container is reachable"
    except OSError:
        return False, f"no live container for {connector_slug} at {host}:{port}"


def _uses_databricks_rest_fixture(connector_slug: str, tool_name: str) -> bool:
    return (
        connector_slug == "databricks"
        and tool_name in DATABRICKS_REST_FIXTURE_TOOLS
        and _manifest_lookup("ACME_SAAS_DATABRICKS_WORKSPACE_API") == "fixture"
    )


def _live_fixture_reason(connector_slug: str, tool_name: str) -> str | None:
    if _uses_databricks_rest_fixture(connector_slug, tool_name):
        return (
            _manifest_lookup("ACME_SAAS_DATABRICKS_WORKSPACE_API_REASON")
            or "Databricks Workspace/Jobs REST APIs unavailable in Acme sandbox."
        )
    if connector_slug == "bigquery" and tool_name in BIGQUERY_JOB_METADATA_FIXTURE_TOOLS:
        return "BigQuery INFORMATION_SCHEMA job metadata is unavailable to the Acme sandbox service account."
    if (
        connector_slug == "databricks"
        and tool_name in DATABRICKS_SQL_FIXTURE_TOOLS
        and _manifest_lookup("ACME_SAAS_DATABRICKS_WORKSPACE_API") == "fixture"
    ):
        return "Databricks SQL Statements API is unavailable in the Acme sandbox."
    if connector_slug == "redshift" and _manifest_lookup("ACME_SAAS_REDSHIFT_CONNECTION_API") == "fixture":
        return (
            _manifest_lookup("ACME_SAAS_REDSHIFT_CONNECTION_API_REASON")
            or "Redshift connection unavailable from Acme CI."
        )
    if (
        connector_slug == "fivetran"
        and tool_name in FIVETRAN_PARTIAL_API_FIXTURE_TOOLS
        and _manifest_lookup("ACME_SAAS_FIVETRAN_SCHEMA_STATUS") == "404"
    ):
        return "Fivetran schema and usage APIs are unavailable for the seeded Acme connector."
    if connector_slug == "github" and tool_name == "read_get_workflow_run_logs":
        target_run_id = _manifest_lookup("ACME_SAAS_GITHUB_WORKFLOW_RUN_ID") or os.getenv("ACME_GITHUB_WORKFLOW_RUN_ID")
        if target_run_id and target_run_id == os.getenv("GITHUB_RUN_ID"):
            return "GitHub does not expose logs for the in-progress Acme workflow run."
    if (
        connector_slug == "notion"
        and tool_name in NOTION_DATABASE_FIXTURE_TOOLS
        and not os.getenv("NOTION_TEST_DATABASE_IDS")
        and not _manifest_lookup("ACME_SAAS_NOTION_DATABASE_ID")
    ):
        return "Notion database APIs are fixture-backed because the Acme sandbox seeds pages, not databases."
    if connector_slug == "notion" and tool_name in NOTION_BLOCK_FIXTURE_TOOLS:
        return "Notion block/comment APIs are fixture-backed because live block reads intermittently time out in Acme CI."
    if connector_slug == "confluence" and _manifest_lookup("ACME_SAAS_CONFLUENCE_API") == "fixture":
        return (
            _manifest_lookup("ACME_SAAS_CONFLUENCE_API_REASON")
            or "Confluence API unavailable in Acme sandbox."
        )
    return None


def _credentials_for_slug(connector_slug: str) -> dict[str, Any]:
    if connector_slug in CONTAINER_CREDENTIALS:
        return dict(CONTAINER_CREDENTIALS[connector_slug])
    if connector_slug == "notion":
        return {
            "integration_token": env_first("NOTION_INTEGRATION_TOKEN", "NOTION_TOKEN"),
            "database_ids": os.environ.get("NOTION_TEST_DATABASE_IDS", ""),
        }
    if connector_slug == "github":
        return {
            "token": env_first("GITHUB_TEST_TOKEN", "GH_TEST_TOKEN"),
            "repositories": _manifest_lookup("ACME_SAAS_GITHUB_REPO") or github_test_repo(),
        }
    if connector_slug == "confluence":
        return {
            "site_url": os.environ.get("CONFLUENCE_SITE_URL"),
            "email": os.environ.get("CONFLUENCE_EMAIL"),
            "api_token": env_first("CONFLUENCE_API_TOKEN", "CONFLUENCE_API_BASIC_AUTH_TOKEN", "CONFLUENCE_API_OAUTH_TOKEN"),
        }
    if connector_slug == "bigquery":
        return {
            "service_account_json": os.environ.get("BIGQUERY_SERVICE_ACCOUNT_JSON"),
            "project_id": os.environ.get("BIGQUERY_PROJECT_ID"),
            "dataset": "acme_analytics",
        }
    if connector_slug == "snowflake":
        return {
            "account": normalize_snowflake_account(os.environ.get("SNOWFLAKE_ACCOUNT") or ""),
            "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE")
            or _manifest_lookup("ACME_SAAS_SNOWFLAKE_WAREHOUSE")
            or DEFAULT_SNOWFLAKE_WAREHOUSE,
            "database": os.environ.get("SNOWFLAKE_DATABASE") or "ACME",
            "schema": os.environ.get("SNOWFLAKE_SCHEMA") or "MARTS",
            "user": os.environ.get("SNOWFLAKE_USER"),
            "password": os.environ.get("SNOWFLAKE_PASSWORD"),
            "private_key": os.environ.get("SNOWFLAKE_PRIVATE_KEY"),
            "private_key_passphrase": os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"),
        }
    if connector_slug == "databricks":
        return {
            "workspace_url": env_first("DATABRICKS_WORKSPACE_URL", "DATABRICKS_HOST"),
            "http_path": os.environ.get("DATABRICKS_HTTP_PATH"),
            "token": os.environ.get("DATABRICKS_TOKEN"),
        }
    if connector_slug == "redshift":
        endpoint = env_first("REDSHIFT_CLUSTER_ENDPOINT", "REDSHIFT_ENDPOINT")
        endpoint_db = parse_redshift_endpoint(endpoint)[2] if endpoint else None
        return {
            "cluster_endpoint": endpoint,
            "database": os.environ.get("REDSHIFT_DATABASE") or endpoint_db or "dev",
            "user": os.environ.get("REDSHIFT_USER"),
            "password": os.environ.get("REDSHIFT_PASSWORD"),
            "cluster_identifier": os.environ.get("REDSHIFT_CLUSTER_IDENTIFIER")
            or (redshift_cluster_identifier(endpoint) if endpoint else None),
        }
    if connector_slug == "fivetran":
        return {"api_key": os.environ.get("FIVETRAN_API_KEY"), "api_secret": os.environ.get("FIVETRAN_API_SECRET")}
    if connector_slug == "openai":
        return {"api_key": os.environ.get("OPENAI_API_KEY"), "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")}
    return {}


def _missing_requirements(names: list[EnvRequirement]) -> list[str]:
    missing: list[str] = []
    for requirement in names:
        if isinstance(requirement, tuple):
            if not env_first(*requirement):
                missing.append(" or ".join(requirement))
            continue
        if not os.getenv(requirement):
            missing.append(requirement)
    return missing


def _flatten_manifest(prefix: str, value: Any, output: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _flatten_manifest(f"{prefix}_{key}" if prefix else str(key), nested, output)
    elif isinstance(value, list):
        output[prefix] = ",".join(str(item) for item in value)
    elif value is not None:
        rendered = str(value)
        output[prefix] = rendered
        output[prefix.upper()] = rendered


def _manifest_lookup(key: str) -> str | None:
    manifest: dict[str, str] = {}
    try:
        _flatten_manifest("ACME", load_acme_ids(), manifest)
    except FileNotFoundError:
        return None
    return manifest.get(key)


def _substitute_placeholders(value: Any) -> Any:
    manifest: dict[str, str] = {}
    try:
        _flatten_manifest("ACME", load_acme_ids(), manifest)
    except FileNotFoundError:
        manifest = {}
    manifest.update({key: val for key, val in os.environ.items() if key.startswith(("ACME_", "GH_", "GITHUB_", "NOTION_", "CONFLUENCE_", "SNOWFLAKE_", "DATABRICKS_", "REDSHIFT_", "FIVETRAN_", "BIGQUERY_"))})
    aliases = {
        "ACME_PAGE_ID": manifest.get("ACME_SAAS_NOTION_CHURN_PAGE_ID") or manifest.get("ACME_NOTION_CHURN_PAGE_ID"),
        "ACME_NOTION_CHURN_PAGE_ID": manifest.get("ACME_SAAS_NOTION_CHURN_PAGE_ID"),
        "ACME_NOTION_RUNBOOK_PAGE_ID": manifest.get("ACME_SAAS_NOTION_RUNBOOK_PAGE_ID"),
        "ACME_NOTION_PARENT": manifest.get("ACME_SAAS_NOTION_PARENT_PAGE_ID") or os.getenv("NOTION_TEST_PARENT_PAGE_ID"),
        "ACME_CONFLUENCE_SPACE_KEY": manifest.get("ACME_SAAS_CONFLUENCE_SPACE_KEY") or os.getenv("CONFLUENCE_SPACE_KEY") or "ACME",
        "ACME_CONFLUENCE_OKR_PAGE_ID": manifest.get("ACME_SAAS_CONFLUENCE_OKR_PAGE_ID"),
        "ACME_CONFLUENCE_ARCHITECTURE_PAGE_ID": manifest.get("ACME_SAAS_CONFLUENCE_ARCHITECTURE_PAGE_ID"),
        "ACME_CONFLUENCE_PIPELINE_PAGE_ID": manifest.get("ACME_SAAS_CONFLUENCE_PIPELINE_PAGE_ID"),
        "GITHUB_TEST_REPO": manifest.get("ACME_SAAS_GITHUB_REPO") or github_test_repo(),
        "SNOWFLAKE_WAREHOUSE": manifest.get("ACME_SAAS_SNOWFLAKE_WAREHOUSE")
        or os.getenv("SNOWFLAKE_WAREHOUSE")
        or DEFAULT_SNOWFLAKE_WAREHOUSE,
        "ACME_GITHUB_HEAD_SHA": manifest.get("ACME_SAAS_GITHUB_HEAD_SHA") or os.getenv("ACME_GITHUB_HEAD_SHA"),
        "ACME_GITHUB_ISSUE_NUMBER": manifest.get("ACME_SAAS_GITHUB_ISSUE_NUMBER") or os.getenv("ACME_GITHUB_ISSUE_NUMBER"),
        "ACME_GITHUB_PR_NUMBER": manifest.get("ACME_SAAS_GITHUB_PR_NUMBER") or os.getenv("ACME_GITHUB_PR_NUMBER"),
        "ACME_GITHUB_WORKFLOW_RUN_REPO": manifest.get("ACME_SAAS_GITHUB_WORKFLOW_RUN_REPO")
        or os.getenv("ACME_GITHUB_WORKFLOW_RUN_REPO")
        or os.getenv("GITHUB_REPOSITORY")
        or manifest.get("ACME_SAAS_GITHUB_REPO")
        or github_test_repo(),
        "ACME_GITHUB_WORKFLOW_RUN_ID": manifest.get("ACME_SAAS_GITHUB_WORKFLOW_RUN_ID")
        or os.getenv("ACME_GITHUB_WORKFLOW_RUN_ID")
        or os.getenv("GITHUB_RUN_ID"),
        "ACME_AIRBYTE_CONNECTION_ID": manifest.get("ACME_CONTAINERS_AIRBYTE_CONNECTION_ID") or os.getenv("ACME_AIRBYTE_CONNECTION_ID"),
        "ACME_AIRBYTE_SOURCE_ID": manifest.get("ACME_CONTAINERS_AIRBYTE_SOURCE_ID") or os.getenv("ACME_AIRBYTE_SOURCE_ID"),
        "ACME_AIRBYTE_DESTINATION_ID": manifest.get("ACME_CONTAINERS_AIRBYTE_DESTINATION_ID") or os.getenv("ACME_AIRBYTE_DESTINATION_ID"),
        "ACME_AIRBYTE_JOB_ID": manifest.get("ACME_CONTAINERS_AIRBYTE_JOB_ID") or os.getenv("ACME_AIRBYTE_JOB_ID"),
        "ACME_FIVETRAN_CONNECTOR_ID": manifest.get("ACME_SAAS_FIVETRAN_CONNECTOR_ID")
        or os.getenv("ACME_FIVETRAN_CONNECTOR_ID")
        or os.getenv("FIVETRAN_CONNECTOR_ID"),
        "ACME_FIVETRAN_DESTINATION_ID": manifest.get("ACME_SAAS_FIVETRAN_DESTINATION_ID")
        or os.getenv("ACME_FIVETRAN_DESTINATION_ID")
        or os.getenv("FIVETRAN_DESTINATION_ID"),
        "REDSHIFT_CLUSTER_IDENTIFIER": manifest.get("ACME_SAAS_REDSHIFT_CLUSTER_IDENTIFIER")
        or os.getenv("REDSHIFT_CLUSTER_IDENTIFIER")
        or (
            redshift_cluster_identifier(env_first("REDSHIFT_CLUSTER_ENDPOINT", "REDSHIFT_ENDPOINT") or "")
            if env_first("REDSHIFT_CLUSTER_ENDPOINT", "REDSHIFT_ENDPOINT")
            else None
        ),
        "ACME_DATABRICKS_NOTEBOOK_PATH": manifest.get("ACME_SAAS_DATABRICKS_NOTEBOOK_PATH")
        or os.getenv("ACME_DATABRICKS_NOTEBOOK_PATH")
        or os.getenv("DATABRICKS_NOTEBOOK_PATH"),
        "ACME_DATABRICKS_JOB_ID": manifest.get("ACME_SAAS_DATABRICKS_JOB_ID")
        or os.getenv("ACME_DATABRICKS_JOB_ID")
        or os.getenv("DATABRICKS_JOB_ID"),
        "ACME_DATABRICKS_RUN_ID": manifest.get("ACME_SAAS_DATABRICKS_RUN_ID")
        or os.getenv("ACME_DATABRICKS_RUN_ID")
        or os.getenv("DATABRICKS_RUN_ID"),
        "ACME_DATABRICKS_CLUSTER_ID": manifest.get("ACME_SAAS_DATABRICKS_CLUSTER_ID")
        or os.getenv("ACME_DATABRICKS_CLUSTER_ID")
        or os.getenv("DATABRICKS_CLUSTER_ID"),
        "ACME_DATABRICKS_TABLE": manifest.get("ACME_SAAS_DATABRICKS_TABLE") or "acme.silver.events",
        "ACME_DATABRICKS_EVENTS_SELECT_SQL": (
            "select event_id, customer_id, event_name from "
            f"{manifest.get('ACME_SAAS_DATABRICKS_TABLE') or 'acme.silver.events'} limit 3"
        ),
        "ACME_DATABRICKS_EVENTS_VIEW": (
            f"{manifest.get('ACME_SAAS_DATABRICKS_CATALOG') or 'acme'}.silver.acme_coverage_events_view"
        ),
        "ACME_DATABRICKS_EVENTS_VIEW_SELECT_SQL": (
            "select event_id, customer_id from "
            f"{manifest.get('ACME_SAAS_DATABRICKS_TABLE') or 'acme.silver.events'} limit 10"
        ),
        "ACME_DBT_PROJECT_PATH": manifest.get("ACME_CONTAINERS_DBT_PROJECT_PATH") or os.getenv("ACME_DBT_PROJECT_PATH", "."),
        "ACME_DBT_RUN_ID": manifest.get("ACME_CONTAINERS_DBT_RUN_ID") or os.getenv("ACME_DBT_RUN_ID", "1"),
        "ACME_PREFECT_FLOW_ID": manifest.get("ACME_CONTAINERS_PREFECT_FLOW_ID") or os.getenv("ACME_PREFECT_FLOW_ID"),
        "ACME_PREFECT_DEPLOYMENT_ID": manifest.get("ACME_CONTAINERS_PREFECT_DEPLOYMENT_ID")
        or os.getenv("ACME_PREFECT_DEPLOYMENT_ID"),
        "ACME_PREFECT_RUN_ID": manifest.get("ACME_CONTAINERS_PREFECT_RUN_ID") or os.getenv("ACME_PREFECT_RUN_ID"),
        "ACME_PREFECT_TASK_RUN_ID": manifest.get("ACME_CONTAINERS_PREFECT_TASK_RUN_ID")
        or os.getenv("ACME_PREFECT_TASK_RUN_ID"),
        "ACME_DAGSTER_RUN_ID": manifest.get("ACME_CONTAINERS_DAGSTER_RUN_ID") or os.getenv("ACME_DAGSTER_RUN_ID"),
        "ACME_DAGSTER_JOB_NAME": manifest.get("ACME_CONTAINERS_DAGSTER_JOB_NAME") or os.getenv("ACME_DAGSTER_JOB_NAME"),
        "ACME_DAGSTER_SENSOR": manifest.get("ACME_CONTAINERS_DAGSTER_SENSOR") or os.getenv("ACME_DAGSTER_SENSOR"),
        "ACME_DAGSTER_SCHEDULE": manifest.get("ACME_CONTAINERS_DAGSTER_SCHEDULE") or os.getenv("ACME_DAGSTER_SCHEDULE"),
        "ACME_DAGSTER_PARTITION": manifest.get("ACME_CONTAINERS_DAGSTER_PARTITION") or os.getenv("ACME_DAGSTER_PARTITION"),
        "ACME_DAGSTER_REPOSITORY_NAME": manifest.get("ACME_CONTAINERS_DAGSTER_REPOSITORY_NAME")
        or os.getenv("ACME_DAGSTER_REPOSITORY_NAME"),
        "ACME_DAGSTER_REPOSITORY_LOCATION_NAME": manifest.get("ACME_CONTAINERS_DAGSTER_REPOSITORY_LOCATION_NAME")
        or os.getenv("ACME_DAGSTER_REPOSITORY_LOCATION_NAME"),
        "TIMESTAMP": datetime.now(UTC).strftime("%Y%m%d%H%M%S"),
    }
    manifest.update({key: val for key, val in aliases.items() if val})
    if isinstance(value, str):
        result = value
        for key, val in manifest.items():
            result = result.replace(f"${key}", val)
        return result
    if isinstance(value, dict):
        return {key: _substitute_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_placeholders(item) for item in value]
    return value


PLACEHOLDER_RE = re.compile(r"\$[A-Z][A-Z0-9_]*")


def _unresolved_placeholders(value: Any) -> list[str]:
    unresolved: list[str] = []
    if isinstance(value, dict):
        for nested in value.values():
            unresolved.extend(_unresolved_placeholders(nested))
    elif isinstance(value, list):
        for nested in value:
            unresolved.extend(_unresolved_placeholders(nested))
    elif isinstance(value, str):
        unresolved.extend(PLACEHOLDER_RE.findall(value))
    return sorted(set(unresolved))


def _assert_shape(result: dict[str, Any], expect_shape: dict[str, Any]) -> None:
    for key, expected in expect_shape.items():
        if key == "status":
            continue
        assert key in result, f"Missing result key {key}; got {sorted(result)}"
        _assert_value_shape(result[key], expected, path=key)


def _assert_read_tool_has_payload(tool_name: str, result: dict[str, Any]) -> None:
    if not tool_name.startswith("read_"):
        return
    payload_keys = set(result) - {"status", "agent_id", "message", "warning", "warnings"}
    assert payload_keys, f"{tool_name} returned no read payload keys; got {sorted(result)}"


def _assert_value_shape(value: Any, expected: Any, *, path: str) -> None:
    if expected == "list":
        assert isinstance(value, list), f"{path} should be a list; got {type(value).__name__}"
        return
    if expected == "non_empty_list":
        assert isinstance(value, list), f"{path} should be a list; got {type(value).__name__}"
        assert value, f"{path} should not be empty"
        return
    if isinstance(expected, str) and expected.startswith("list_min_"):
        minimum = int(expected.removeprefix("list_min_"))
        assert isinstance(value, list), f"{path} should be a list; got {type(value).__name__}"
        assert len(value) >= minimum, f"{path} should have at least {minimum} item(s); got {len(value)}"
        return
    if expected == "dict":
        assert isinstance(value, dict), f"{path} should be a dict; got {type(value).__name__}"
        return
    if expected == "str":
        assert isinstance(value, str), f"{path} should be a string; got {type(value).__name__}"
        return
    if expected == "int":
        assert isinstance(value, int), f"{path} should be an int; got {type(value).__name__}"
        return
    if expected == "positive_int":
        assert isinstance(value, int), f"{path} should be an int; got {type(value).__name__}"
        assert value > 0, f"{path} should be positive; got {value}"
        return
    if isinstance(expected, dict):
        assert isinstance(value, dict), f"{path} should be a dict; got {type(value).__name__}"
        for nested_key, nested_expected in expected.items():
            assert nested_key in value, f"Missing result key {path}.{nested_key}; got {sorted(value)}"
            _assert_value_shape(value[nested_key], nested_expected, path=f"{path}.{nested_key}")


def _record_live_result(
    connector_slug: str,
    tool_name: str,
    *,
    status: str,
    started_at: datetime,
    detail: dict[str, Any],
) -> None:
    raw_path = os.getenv("ACME_COVERAGE_RESULTS_FILE")
    if not raw_path:
        return
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = json.loads(path.read_text()) if path.exists() else []
    finished_at = datetime.now(UTC)
    rows.append(
        {
            "connector": connector_slug,
            "tool": tool_name,
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "latency_ms": int((finished_at - started_at).total_seconds() * 1000),
            "detail": detail,
        }
    )
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
