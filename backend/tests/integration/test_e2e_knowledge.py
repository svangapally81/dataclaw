from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_v03_knowledge_acceptance_gate() -> None:
    if os.getenv("RUN_OPENAI_E2E") != "1" or not os.getenv("OPENAI_API_KEY"):
        pytest.skip("RUN_OPENAI_E2E=1 and OPENAI_API_KEY are required for the v0.3 real-OpenAI gate.")
    if not os.getenv("DATACLAW_API_URL"):
        pytest.fail("DATACLAW_API_URL must point at a running DataClaw API for the v0.3 acceptance gate.")

    # The full gate is intentionally explicit so CI does not silently replace it with a mock.
    # It is run from the integration compose target after mock services and Chroma are up.
    base_url = os.environ["DATACLAW_API_URL"]
    async with AsyncClient(base_url=base_url, timeout=120) as client:
        login = await client.post(
            "/auth/login",
            json={"email": "admin@dataclaw.local", "password": "dataclaw-local-admin"},
        )
        login.raise_for_status()

        postgres_database_url = "postgresql+asyncpg://dataclaw:dataclaw@localhost:15432/dataclaw_integration"
        credentials = {
            "postgres": {
                "database_url": postgres_database_url
            },
            "notion": {"base_url": "http://localhost:18084", "integration_token": "fixture"},
            "github": {
                "base_url": "http://localhost:18084",
                "token": "fixture",
                "repositories": "acme/warehouse",
            },
            "airflow": {"base_url": "http://localhost:18084", "username": "fixture", "password": "fixture"},
            "dbt": {
                "base_url": "http://localhost:18084/api/v2/accounts/1",
                "api_token": "fixture",
                "account_id": "1",
            },
        }
        for slug, connector_credentials in credentials.items():
            test_response = await client.post(
                f"/connectors/{slug}/test",
                json={"credentials": connector_credentials, "persist_on_success": True},
            )
            assert test_response.status_code == 200, test_response.text
            assert test_response.json()["status"] == "ok"
            sync_response = await client.post(f"/connectors/{slug}/sync")
            assert sync_response.status_code == 200, sync_response.text
            assert sync_response.json().get("ingestion", {}).get("pages_written", 0) >= 1

        pages_response = await client.get("/knowledge/pages")
        pages_response.raise_for_status()
        pages = pages_response.json()
        pages_by_path = {page["path"]: page for page in pages}
        assert len(pages) >= 12
        expected_paths = {
            "wiki/postgres/orders.md",
            "wiki/postgres/customers.md",
            "wiki/notion/data-glossary.md",
            "wiki/notion/metrics-handbook.md",
            "wiki/airflow/daily-orders-refresh.md",
            "wiki/dbt/fct-revenue-daily.md",
        }
        assert expected_paths.issubset(pages_by_path)
        assert any(page["source_type"] == "github" and "readme" in page["path"] for page in pages)
        for page in pages_by_path.values():
            disk_path = Path(page["disk_path"])
            assert disk_path.exists()
            disk_markdown = disk_path.read_text(encoding="utf-8")
            assert page["body"] in disk_markdown
            assert page["content_hash"]
        assert "orders" in pages_by_path["wiki/postgres/orders.md"]["body"].lower()
        assert "ltv" in pages_by_path["wiki/notion/metrics-handbook.md"]["body"].lower()
        assert "produces" in pages_by_path["wiki/airflow/daily-orders-refresh.md"]["frontmatter"]
        assert "depends_on" in pages_by_path["wiki/dbt/fct-revenue-daily.md"]["frontmatter"]

        compile_response = await client.post("/knowledge/compile")
        compile_response.raise_for_status()
        compile_stats = compile_response.json()
        assert compile_stats["nodes_created"] + compile_stats["nodes_updated"] >= 8
        graph_response = await client.get("/knowledge/graph?root=orders&depth=2")
        graph_response.raise_for_status()
        graph = graph_response.json()
        assert len(graph["edges"]) >= 6
        node_names = {node["canonical_name"] for node in graph["nodes"]}
        edge_relationships = {edge["relationship"] for edge in graph["edges"]}
        assert any("order" in name for name in node_names)
        assert "describes" in edge_relationships

        agents_response = await client.get("/agents")
        agents_response.raise_for_status()
        chat_agent = next(agent for agent in agents_response.json() if agent["name"] == "chat")
        grant_response = await client.put(
            f"/agents/{chat_agent['id']}/grants",
            json={"grants": [{"connector_slug": "postgres", "read_enabled": True, "write_enabled": True}]},
        )
        grant_response.raise_for_status()
        setup_engine = create_async_engine(postgres_database_url)
        try:
            async with setup_engine.begin() as conn:
                await conn.execute(text("drop table if exists test_summary"))
                await conn.execute(text("create table test_summary (month text)"))
        finally:
            await setup_engine.dispose()

        scenarios = [
            ("Tell me about the orders table.", ["orders", "customer"], ["wiki/postgres/orders.md"], False, False),
            (
                "What does the data glossary say about LTV?",
                ["ltv"],
                ["wiki/notion/metrics-handbook.md", "wiki/notion/data-glossary.md"],
                False,
                False,
            ),
            (
                "What pipelines produce or consume the orders table?",
                ["daily_orders_refresh", "stg_orders"],
                ["wiki/airflow/daily-orders-refresh.md", "wiki/dbt/stg-orders.md"],
                False,
                False,
            ),
            ("How many orders did we get last week, broken down by customer segment?", ["orders"], ["wiki/postgres/orders.md"], False, False),
            ("Show me revenue by month as a chart.", ["revenue"], ["wiki/notion/metrics-handbook.md"], False, False),
            ("Drop the postgres test_summary table.", ["approval"], [], False, True),
        ]
        pending_alert_id = None
        for prompt, _expected_terms, expected_paths, expects_chart, expects_approval in scenarios:
            response = await client.post("/ide/chat", json={"question": prompt})
            response.raise_for_status()
            payload = response.json()
            assert payload["answer"]
            citation_paths = {citation.get("path") for citation in payload.get("citations", [])}
            if expected_paths:
                assert citation_paths
            if expects_chart:
                assert payload.get("chart_spec")
                assert payload["chart_spec"].get("$schema", "").endswith("vega-lite/v5.json")
                assert len(payload["chart_spec"].get("data", {}).get("values", [])) <= 12
            if expects_approval:
                assert payload.get("status") == "pending_approval"
                assert payload.get("alert_id")
                pending_alert_id = payload["alert_id"]
                table_check = await client.post(
                    "/ide/query",
                    json={"sql": "select count(*) as rows from test_summary", "connector_slug": "postgres"},
                )
                table_check.raise_for_status()

        assert pending_alert_id
        approve_response = await client.post(f"/alerts/{pending_alert_id}/approve-and-execute")
        approve_response.raise_for_status()
        assert approve_response.json()["status"] == "executed"
        dropped_check = await client.post(
            "/ide/query",
            json={"sql": "select count(*) as rows from test_summary", "connector_slug": "postgres"},
        )
        assert dropped_check.status_code == 400
        audit_response = await client.get("/audit?slug=postgres")
        audit_response.raise_for_status()
        assert any(row["alert_id"] == pending_alert_id and row["required_approval"] for row in audit_response.json())

        metrics_path = Path(pages_by_path["wiki/notion/metrics-handbook.md"]["disk_path"])
        original_metrics = metrics_path.read_text(encoding="utf-8")
        override = "\n\n## User override\n\nLTV OVERRIDE: LTV is support-adjusted lifetime revenue minus refund exposure.\n"
        metrics_path.write_text(original_metrics.rstrip() + override, encoding="utf-8")
        future_mtime = time.time() + 2
        os.utime(metrics_path, (future_mtime, future_mtime))

        reconcile_response = await client.post("/knowledge/reconcile")
        reconcile_response.raise_for_status()
        assert reconcile_response.json()["pages_changed"] >= 1
        recompile_response = await client.post("/knowledge/compile")
        recompile_response.raise_for_status()
        assert recompile_response.json()["nodes_updated"] >= 1

        ltv_response = await client.post("/ide/chat", json={"question": "What's LTV?"})
        ltv_response.raise_for_status()
        assert "support-adjusted lifetime revenue" in ltv_response.json()["answer"].lower()
