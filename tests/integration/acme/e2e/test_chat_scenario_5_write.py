from __future__ import annotations

import pytest

from tests.integration.acme.e2e.helpers import (
    assert_answer_contains,
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
async def test_chat_scenario_5_append_runbook_approval_flow(acme_client) -> None:
    await configure_connectors(acme_client, "confluence")
    await grant_chat_write(acme_client, "confluence")
    before_ids = await event_ids(acme_client)
    payload = await chat(acme_client, "Append today's deployment to the on-call runbook")
    calls = await chat_tool_calls(acme_client, payload, before_ids)
    assert_tool_called(calls, "confluence.write_append_to_page")
    assert payload.get("status") == "pending_approval", payload
    assert payload.get("alert_id"), payload
    approve = await acme_client.post(f"/alerts/{payload['alert_id']}/approve-and-execute")
    approve.raise_for_status()
    approve_payload = approve.json()
    assert approve_payload["status"] == "executed"
    assert (approve_payload.get("result") or {}).get("status") in {"ok", "updated"}, approve_payload
    audit = await acme_client.get("/audit", params={"slug": "confluence"})
    audit.raise_for_status()
    rows = audit.json()
    assert any(
        row.get("connector_slug") == "confluence"
        and row.get("statement_type") == "APPEND_TO_PAGE"
        and (
            row.get("alert_id") == payload["alert_id"]
            or "write_append_to_page" in str(row.get("statement") or "")
        )
        for row in rows
    ), rows
    assert_answer_contains(payload, "approval")
    await assert_no_error_events(acme_client, before_ids)
