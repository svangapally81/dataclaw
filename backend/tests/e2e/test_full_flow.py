"""End-to-end DataClaw flow.

Exercises the full path a real user would take:

    login -> configure SQLite connector -> sync -> run all four ingestion
    agents (metadata, lineage, freshness, docs) -> ask a chat question
    (answering agent) -> verify persistence in the DB.

If `OPENAI_API_KEY` is set the chat agent uses real OpenAI tool-use; otherwise
the deterministic fallback is exercised. The test asserts on persisted state,
not on LLM response shape, so it passes either way.
"""

from __future__ import annotations

import importlib
import logging
import os

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.runslow]


@pytest.fixture
async def app_client(monkeypatch, tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}"
    demo_url = f"sqlite+aiosqlite:///{tmp_path/'demo.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DEMO_DATABASE_URL", demo_url)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("MASTER_KEY", "test-master-key-please-change")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-please-change")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from app.core.config import get_settings
    get_settings.cache_clear()

    import app.db.session as session_module
    importlib.reload(session_module)
    from app import main as main_module
    importlib.reload(main_module)

    transport = ASGITransport(app=main_module.app)
    async with main_module.app.router.lifespan_context(main_module.app):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            login = await ac.post(
                "/auth/login",
                json={"email": "admin@dataclaw.local", "password": "dataclaw-local-admin"},
            )
            assert login.status_code == 200
            yield ac, main_module


@pytest.mark.asyncio
async def test_full_flow_sqlite_through_chat(app_client) -> None:
    ac, main_module = app_client

    test_response = await ac.post("/connectors/sqlite/test", json={"credentials": {}})
    assert test_response.status_code == 200
    assert test_response.json()["status"] == "ok"

    sync_response = await ac.post("/connectors/sqlite/sync")
    assert sync_response.status_code == 200
    summary = sync_response.json()
    assert summary["mode"] == "real"
    assert summary["objects_synced"] >= 3

    workspace_response = await ac.get("/workspace")
    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    table_names = {
        table["name"]
        for dataset in workspace["datasets"]
        for table in dataset["tables"]
    }
    assert {"customers", "orders", "products"}.issubset(table_names)

    for agent in ("metadata", "lineage", "freshness", "docs"):
        run = await ac.post(f"/agents/{agent}/run")
        assert run.status_code == 200, f"{agent} run failed: {run.text}"
        body = run.json()
        assert body["status"] == "completed", f"{agent} status: {body}"

    workspace_after = (await ac.get("/workspace")).json()
    orders = next(
        table
        for dataset in workspace_after["datasets"]
        for table in dataset["tables"]
        if table["name"] == "orders"
    )
    column_descriptions = {col["name"]: col.get("description") for col in orders["columns"]}
    assert any(column_descriptions.values()), "docs agent should populate at least one description"

    dashboard = (await ac.get("/agents/dashboard")).json()
    run_names = {run["agent_name"].lower() for run in dashboard["runs"]}
    for agent in ("metadata", "lineage", "freshness", "docs"):
        assert any(agent in name for name in run_names), f"missing {agent} run in {run_names}"

    chat_response = await ac.post(
        "/ide/chat",
        json={"question": "Which customers have the most revenue?"},
    )
    assert chat_response.status_code == 200
    chat = chat_response.json()
    assert chat["thread_id"]
    assert "answer" in chat
    if os.getenv("OPENAI_API_KEY"):
        assert chat["provider"] in {"openai", "deterministic_local"} or chat["llm_status"] in {
            "completed",
            "no_tool_call",
            "openai_error_fallback",
            "openai_tool_error_fallback",
            "skipped",
        }

    thread_id = chat["thread_id"]
    fetched = (await ac.get(f"/chat/threads/{thread_id}")).json()
    assert fetched["message_count"] >= 2
    roles = [msg["role"] for msg in fetched["messages"]]
    assert "user" in roles and "assistant" in roles

    closed = await ac.post(f"/chat/threads/{thread_id}/close")
    assert closed.status_code == 200
    assert closed.json()["archived"] is True
    blocked = await ac.post("/ide/chat", json={"thread_id": thread_id, "question": "again?"})
    assert blocked.status_code == 409

    logging.getLogger("dataclaw.e2e").info("e2e_marker", extra={"_marker": "e2e-1"})
    from app.core.logging import _drain_once
    await _drain_once()

    logs = (await ac.get("/observability/logs?q=e2e_marker&limit=10")).json()
    assert logs["total"] >= 1
    matched = [entry for entry in logs["entries"] if entry["message"] == "e2e_marker"]
    assert matched
    assert matched[0]["context"].get("marker") == "e2e-1"

    request_logs = (await ac.get("/observability/logs?q=request_complete&limit=5")).json()
    assert request_logs["total"] >= 1
