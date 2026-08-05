from __future__ import annotations

import pytest

from tests.integration.acme.common import EXPECTED_ACME_CONNECTORS, load_acme_ids
from tests.integration.acme.e2e.helpers import (
    compile_workspace,
    configure_connectors,
    retrieve_sources,
)

pytestmark = pytest.mark.integration


def test_acme_seed_manifest_has_compile_sources() -> None:
    manifest = load_acme_ids()
    assert manifest["company"] == "Acme Co"
    assert "containers" in manifest
    assert "saas" in manifest


@pytest.mark.asyncio
async def test_acme_compile_creates_expected_graph_size(acme_client) -> None:
    await configure_connectors(acme_client, *EXPECTED_ACME_CONNECTORS)
    result = await compile_workspace(acme_client)
    assert result["nodes_created"] + result.get("nodes_updated", 0) >= 50
    assert result["edges_created"] + result.get("edges_updated", 0) >= 100


@pytest.mark.asyncio
async def test_retrieval_for_churn_question(acme_client) -> None:
    await configure_connectors(acme_client, "notion", "snowflake")
    await compile_workspace(acme_client)
    sources = [source.lower() for source in await retrieve_sources(acme_client, "how do we define churn?")]
    assert any("notion" in source and "churn" in source for source in sources), sources
    assert any("snowflake" in source and "churn_events" in source for source in sources), sources


@pytest.mark.asyncio
async def test_retrieval_for_pipeline_question(acme_client) -> None:
    await configure_connectors(acme_client, "airflow", "prefect")
    await compile_workspace(acme_client)
    sources = [source.lower() for source in await retrieve_sources(acme_client, "what pipeline updates revenue_daily?")]
    assert any("airflow" in source or "prefect" in source or "acme_revenue_recalc" in source for source in sources), sources
