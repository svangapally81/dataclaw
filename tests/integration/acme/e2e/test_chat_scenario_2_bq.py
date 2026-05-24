from __future__ import annotations

import pytest

from tests.integration.acme.e2e.helpers import (
    assert_answer_contains,
    assert_no_error_events,
    assert_tool_prefix,
    chat,
    chat_tool_calls,
    configure_connectors,
    event_ids,
    grant_chat_write,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_chat_scenario_2_orders_to_arr_lineage(acme_client) -> None:
    await configure_connectors(acme_client, "bigquery", "dbt", "confluence")
    await grant_chat_write(acme_client, "bigquery", "dbt", "confluence")
    before_ids = await event_ids(acme_client)
    payload = await chat(acme_client, "What's the lineage from raw orders to ARR and where's it documented?")
    calls = await chat_tool_calls(acme_client, payload, before_ids)
    assert_tool_prefix(calls, "bigquery.read_", "confluence.read_")
    assert any(call in calls for call in {"dbt.read_get_lineage", "dbt.read_get_model_source", "dbt.read_get_model_docs"}), calls
    assert_answer_contains(payload, "fct_orders", "Postgres", "BigQuery", "pipeline")
    await assert_no_error_events(acme_client, before_ids)
