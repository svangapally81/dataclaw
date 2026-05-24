from __future__ import annotations

import pytest

from tests.integration.acme.e2e.helpers import (
    assert_answer_contains,
    assert_answer_contains_any,
    assert_answer_matches,
    assert_no_error_events,
    chat,
    chat_tool_calls,
    configure_connectors,
    event_ids,
    grant_chat_write,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_chat_scenario_4_authoritative_arr_by_segment(acme_client) -> None:
    await configure_connectors(acme_client, "bigquery", "snowflake", "postgres")
    await grant_chat_write(acme_client, "bigquery", "snowflake", "postgres")
    before_ids = await event_ids(acme_client)
    payload = await chat(acme_client, "Show me ARR by segment - find the most authoritative source")
    calls = await chat_tool_calls(acme_client, payload, before_ids)
    assert any(call.startswith(("bigquery.read_", "snowflake.read_")) for call in calls), calls
    assert not {"bigquery.read_query_select", "snowflake.read_query_select"}.isdisjoint(calls), calls
    assert_answer_contains(payload, "arr", "segment")
    assert_answer_contains_any(payload, ("bigquery", "snowflake"))
    assert_answer_matches(payload, r"(\$|usd).*\d|\d.*(\$|usd)")
    await assert_no_error_events(acme_client, before_ids)
