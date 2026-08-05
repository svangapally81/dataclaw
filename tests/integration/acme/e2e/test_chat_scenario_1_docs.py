from __future__ import annotations

import pytest

from tests.integration.acme.e2e.helpers import (
    assert_answer_contains,
    assert_answer_contains_any,
    assert_no_error_events,
    assert_tool_called,
    chat,
    chat_tool_calls,
    configure_connectors,
    event_ids,
    grant_chat_write,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_chat_scenario_1_churn_spike_docs_and_dag(acme_client) -> None:
    await configure_connectors(acme_client, "notion", "airflow", "postgres")
    await grant_chat_write(acme_client, "notion", "airflow", "postgres")
    before_ids = await event_ids(acme_client)
    payload = await chat(acme_client, "Why did churn spike last week and which DAG owns the calculation?")
    calls = await chat_tool_calls(acme_client, payload, before_ids)
    assert any(call in calls for call in {"notion.read_search_pages", "notion.read_get_page"}), calls
    assert any(call in calls for call in {"airflow.read_list_dags", "airflow.read_get_run", "airflow.read_get_dag_source"}), calls
    assert_tool_called(calls, "postgres.read_query_select")
    assert_answer_contains(payload, "acme_churn_calc", "churn")
    assert_answer_contains_any(payload, ("30 days", "30-day", "successful order"), ("cancel", "downgrade", "paying customer"))
    await assert_no_error_events(acme_client, before_ids)
