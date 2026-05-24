from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="module")
async def client(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("chat-logs-app")
    db_url = f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}"
    demo_url = f"sqlite+aiosqlite:///{tmp_path/'demo.sqlite'}"
    os.environ["DATABASE_URL"] = db_url
    os.environ["DEMO_DATABASE_URL"] = demo_url
    os.environ["DEMO_MODE"] = "true"
    os.environ["MASTER_KEY"] = "test-master-key-please-change"
    os.environ["SESSION_SECRET"] = "test-session-secret-please-change"
    os.environ["DATACLAW_VECTOR_TEST_DOUBLE"] = "true"
    os.environ["DATACLAW_TEST_AUTO_CREATE_SCHEMA"] = "true"
    os.environ["DATACLAW_BCRYPT_ROUNDS"] = "4"

    import importlib

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
async def test_low_memory_warning_only_for_ollama(client, monkeypatch, caplog) -> None:
    _, main_module = client
    monkeypatch.setattr(main_module.settings, "llm_provider", "ollama")
    monkeypatch.setattr(main_module, "_total_memory_bytes", lambda: 4 * 1024**3)

    with caplog.at_level(logging.WARNING, logger="dataclaw.api"):
        main_module._warn_if_low_ollama_memory()

    assert "ollama_low_memory" in caplog.text


@pytest.mark.asyncio
async def test_chat_thread_lifecycle(client) -> None:
    ac, _ = client
    create = await ac.post("/chat/threads", json={"title": "First thread"})
    assert create.status_code == 200
    thread_id = create.json()["id"]

    listed = await ac.get("/chat/threads")
    assert listed.status_code == 200
    assert any(t["id"] == thread_id for t in listed.json())

    closed = await ac.post(f"/chat/threads/{thread_id}/close")
    assert closed.status_code == 200
    assert closed.json()["archived"] is True
    assert closed.json()["archived_at"]

    listed = await ac.get("/chat/threads")
    assert all(t["id"] != thread_id for t in listed.json())

    listed_with_archived = await ac.get("/chat/threads?include_archived=true")
    assert any(t["id"] == thread_id and t["archived"] for t in listed_with_archived.json())

    blocked = await ac.post("/ide/chat", json={"thread_id": thread_id, "question": "hi"})
    assert blocked.status_code == 409

    reopened = await ac.post(f"/chat/threads/{thread_id}/reopen")
    assert reopened.status_code == 200
    assert reopened.json()["archived"] is False

    deleted = await ac.delete(f"/chat/threads/{thread_id}")
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_chat_stream_persists_messages(client) -> None:
    ac, _ = client
    async with ac.stream(
        "POST",
        "/ide/chat",
        headers={"accept": "text/event-stream"},
        json={"question": "Say exactly: streaming check"},
    ) as response:
        assert response.status_code == 200
        body = "".join([chunk async for chunk in response.aiter_text()])

    assert "event: delta" in body
    assert "event: done" in body
    done_frame = next(frame for frame in body.split("\n\n") if frame.startswith("event: done"))
    thread_frame = next(frame for frame in body.split("\n\n") if frame.startswith("event: thread"))
    thread_data = json.loads(next(line for line in thread_frame.splitlines() if line.startswith("data: ")).removeprefix("data: "))
    assert thread_data["run_id"]
    done_data = next(line for line in done_frame.splitlines() if line.startswith("data: "))
    payload = json.loads(done_data.removeprefix("data: "))
    assert payload["thread_id"]
    assert "retrieval_trace" in payload

    fetched = (await ac.get(f"/chat/threads/{payload['thread_id']}")).json()
    assert fetched["message_count"] == 2
    assert [message["role"] for message in fetched["messages"]] == ["user", "assistant"]
    assert fetched["messages"][1]["retrieval_trace"] == payload["retrieval_trace"]


@pytest.mark.asyncio
async def test_chat_run_cancel_endpoint_marks_running_run_cancelled(client) -> None:
    ac, main_module = client
    from sqlalchemy import select

    from app.models.domain import AgentRun, Workspace

    async for db in main_module.get_session():
        workspace = await db.scalar(select(Workspace).limit(1))
        assert workspace is not None
        run = AgentRun(
            workspace_id=workspace.id,
            agent_name="chat",
            status="running",
            state="running",
            summary="streaming",
            timeline=[],
        )
        db.add(run)
        await db.commit()
        run_id = run.id
        break

    cancelled = await ac.post(f"/chat/runs/{run_id}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"


@pytest.mark.asyncio
async def test_observability_events_include_agent_run_tool_calls(client) -> None:
    ac, main_module = client
    from sqlalchemy import select

    from app.models.domain import AgentRun, AgentToolCall, Workspace

    async for db in main_module.get_session():
        workspace = await db.scalar(select(Workspace).limit(1))
        assert workspace is not None
        run = AgentRun(
            workspace_id=workspace.id,
            agent_name="Compile",
            status="completed",
            state="completed",
            summary="compiled graph",
            timeline=[{"step": "compile", "status": "ok"}],
        )
        db.add(run)
        await db.flush()
        run_id = run.id
        db.add(
            AgentToolCall(
                run_id=run_id,
                agent_name="Compile",
                tool_name="query",
                connector_slug="postgres",
                args_json={"sql": "select 1"},
                result_summary="1 row",
                result_size_bytes=8,
                latency_ms=12,
                status="ok",
                called_at=datetime.now(UTC),
            )
        )
        await db.commit()
        break

    response = await ac.get("/observability/events?kind=agent_run&q=Compile")

    assert response.status_code == 200
    event = next(item for item in response.json()["events"] if item["id"] == run_id)
    assert event["tool_calls"] == [
        {
            "id": event["tool_calls"][0]["id"],
            "run_id": run_id,
            "agent_name": "Compile",
            "tool_name": "query",
            "connector_slug": "postgres",
            "args_json": {"sql": "select 1"},
            "result_summary": "1 row",
            "result_size_bytes": 8,
            "latency_ms": 12,
            "status": "ok",
            "error_message": None,
            "called_at": event["tool_calls"][0]["called_at"],
        }
    ]


@pytest.mark.asyncio
async def test_logs_persisted_and_queryable(client) -> None:
    ac, main_module = client
    logger = logging.getLogger("dataclaw.test")
    logger.info("hello_world", extra={"_marker": "abc-123"})

    from app.core.logging import _drain_once
    drained = await _drain_once()
    assert drained >= 1

    response = await ac.get("/observability/logs?q=hello_world&limit=20")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    matched = [e for e in payload["entries"] if e["message"] == "hello_world"]
    assert matched
    assert matched[0]["context"].get("marker") == "abc-123"


@pytest.mark.asyncio
async def test_logs_endpoint_filters_level(client) -> None:
    ac, _ = client
    logger = logging.getLogger("dataclaw.test_filters")
    logger.info("info_event")
    logger.warning("warn_event")
    from app.core.logging import _drain_once
    await _drain_once()

    warn_only = await ac.get("/observability/logs?level=WARNING&limit=50")
    assert warn_only.status_code == 200
    levels = {e["level"] for e in warn_only.json()["entries"]}
    assert levels == {"WARNING"} or levels == set() or levels.issubset({"WARNING"})
