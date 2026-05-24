from __future__ import annotations

import pytest

from tests.integration.acme.e2e.helpers import (
    assert_answer_contains,
    assert_answer_matches,
    assert_no_error_events,
    assert_tool_called,
    assert_tool_prefix,
    chat,
    chat_tool_calls,
    configure_connectors,
    event_ids,
    grant_chat_write,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_chat_scenario_3_revenue_freshness_and_prefect_flow(acme_client) -> None:
    await configure_connectors(acme_client, "snowflake", "prefect")
    await grant_chat_write(acme_client, "snowflake", "prefect")
    before_ids = await event_ids(acme_client)
    payload = await chat(acme_client, "How fresh is our revenue table and which Prefect flow updates it?")
    calls = await chat_tool_calls(acme_client, payload, before_ids)
    assert_tool_prefix(calls, "snowflake.read_")
    assert_tool_called(calls, "prefect.read_list_flows")
    assert_answer_contains(payload, "acme_revenue_recalc", "revenue")
    assert_answer_matches(payload, r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}:\d{2}\b")
    await assert_no_error_events(acme_client, before_ids)
