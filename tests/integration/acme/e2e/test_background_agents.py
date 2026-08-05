from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from tests.integration.acme.e2e.helpers import (
    assert_no_error_events,
    configure_connectors,
    event_ids,
    write_runbook_disk_edit,
)

pytestmark = pytest.mark.integration


def _assert_agent_run(payload: dict, *, summary_contains: str | None = None) -> None:
    assert payload.get("id"), payload
    assert payload.get("status") == "completed", payload
    assert isinstance(payload.get("timeline"), list) and payload["timeline"], payload
    if summary_contains:
        assert summary_contains.lower() in str(payload.get("summary") or "").lower(), payload


async def _run_agent(client, name: str, *, summary_contains: str | None = None) -> dict:
    response = await client.post(f"/agents/{name}/run")
    response.raise_for_status()
    payload = response.json()
    _assert_agent_run(payload, summary_contains=summary_contains)
    return payload


async def _alert_details(client, query: str) -> list[str]:
    response = await client.get("/observability/events", params={"kind": "alert", "q": query, "limit": 50})
    response.raise_for_status()
    return [str(alert.get("detail") or "") for alert in response.json().get("events", [])]


async def _force_bigquery_dim_customers_pre_drift_snapshot() -> None:
    if os.getenv("DATACLAW_API_URL"):
        pytest.skip("Acme schema-drift setup requires the in-process app database.")
    from app.db.session import SessionLocal
    from app.models.domain import Connector, Dataset, TableAsset

    async with SessionLocal() as session:
        connector = await session.scalar(select(Connector).where(Connector.slug == "bigquery"))
        if connector is None:
            pytest.skip("BigQuery connector is not configured in the Acme app database.")
        table = await session.scalar(
            select(TableAsset)
            .join(Dataset)
            .where(
                Dataset.connector_id == connector.id,
                TableAsset.name == "dim_customers",
            )
        )
        if table is None or not table.columns:
            pytest.skip("BigQuery dim_customers table metadata is not available for drift setup.")
        columns = []
        changed = False
        for column in table.columns:
            column = dict(column)
            if str(column.get("name") or "").lower() == "cust_id":
                column["name"] = "customer_id"
                changed = True
            columns.append(column)
        if not changed:
            columns.append({"name": "customer_id", "type": "string", "description": "pre-drift customer key"})
        table.columns = columns
        await session.commit()


@pytest.mark.asyncio
async def test_ingestion_agent_grows_chroma(acme_client) -> None:
    await configure_connectors(acme_client, "notion", "postgres", sync=False)
    before_ids = await event_ids(acme_client)
    before = await acme_client.get("/knowledge/search", params={"q": "Acme", "layer": "all", "limit": 50})
    before.raise_for_status()
    before_count = len(before.json().get("results", []))
    run = await _run_agent(acme_client, "ingestion", summary_contains="auto-synced")
    assert any(item.get("slug") in {"notion", "postgres"} and item.get("status") == "ok" for item in run["timeline"]), run
    after = await acme_client.get("/knowledge/search", params={"q": "Acme", "layer": "all", "limit": 50})
    after.raise_for_status()
    results = after.json().get("results", [])
    assert len(results) > before_count
    assert any("acme" in str(item).lower() for item in results), results
    await assert_no_error_events(acme_client, before_ids)


@pytest.mark.asyncio
async def test_freshness_agent_flags_stale_table(acme_client) -> None:
    await configure_connectors(acme_client, "bigquery")
    before_ids = await event_ids(acme_client)
    await _run_agent(acme_client, "freshness", summary_contains="checked")
    await _run_agent(acme_client, "freshness", summary_contains="flagged")
    details = await _alert_details(acme_client, "dim_customers")
    assert any("dim_customers" in detail and "stale" in detail.lower() for detail in details), details
    workspace = await acme_client.get("/workspace")
    workspace.raise_for_status()
    tables = [
        table
        for dataset in workspace.json().get("datasets", [])
        if dataset.get("source_type") == "bigquery"
        for table in dataset.get("tables", [])
    ]
    assert any(table.get("name") == "dim_customers" and table.get("freshness_status") == "stale" for table in tables), tables
    await assert_no_error_events(acme_client, before_ids)


@pytest.mark.asyncio
async def test_data_quality_agent_detects_drift(acme_client) -> None:
    await configure_connectors(acme_client, "postgres", "bigquery")
    await _force_bigquery_dim_customers_pre_drift_snapshot()
    before_ids = await event_ids(acme_client)
    await _run_agent(acme_client, "data_quality", summary_contains="queries")
    details = await _alert_details(acme_client, "cust_id")
    assert any("customer_id" in detail and "cust_id" in detail for detail in details), details
    await assert_no_error_events(acme_client, before_ids)


@pytest.mark.asyncio
async def test_alerting_agent_picks_up_failed_dag(acme_client) -> None:
    await configure_connectors(acme_client, "airflow")
    before_ids = await event_ids(acme_client)
    await _run_agent(acme_client, "alerting", summary_contains="scanned")
    details = await _alert_details(acme_client, "acme_churn_calc")
    assert any("acme_churn_calc" in detail and "failed" in detail.lower() for detail in details), details
    await assert_no_error_events(acme_client, before_ids)


@pytest.mark.asyncio
async def test_reconciliation_agent_picks_up_disk_edit(acme_client) -> None:
    await configure_connectors(acme_client, "notion")
    before_ids = await event_ids(acme_client)
    await write_runbook_disk_edit(acme_client, "# edited on disk\n\nAcme reconciliation marker.\n")
    run = await _run_agent(acme_client, "reconciliation", summary_contains="reconciled")
    assert "1" in str(run.get("summary") or ""), run
    pages = await acme_client.get("/knowledge/pages")
    pages.raise_for_status()
    assert any("reconciliation marker" in str(page.get("body") or "").lower() for page in pages.json()), pages.json()
    search = await acme_client.get("/knowledge/search", params={"q": "reconciliation marker", "layer": "wiki", "limit": 10})
    search.raise_for_status()
    assert any("reconciliation marker" in str(item).lower() for item in search.json().get("results", []))
    await assert_no_error_events(acme_client, before_ids)
