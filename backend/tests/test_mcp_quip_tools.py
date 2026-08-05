from __future__ import annotations

import os

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import encrypt_json
from app.db.base import Base
from app.models.domain import Connector, Workspace
from app.services.mcp_executor import _kb_tool


@pytest.fixture(scope="module")
async def quip_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("quip")
    os.environ["MASTER_KEY"] = "test-master-key-please-change"
    get_settings.cache_clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'app.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="Test")
        session.add(workspace)
        await session.flush()
        session.add(
            Connector(
                workspace_id=workspace.id,
                slug="quip",
                category="knowledge_base",
                display_name="Quip",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"base_url": "http://quip", "access_token": "quip-secret"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_quip_reads_use_expected_endpoints(quip_session: AsyncSession) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), dict(request.url.params)))
        assert request.headers["Authorization"] == "Bearer quip-secret"
        if request.url.path == "/1/threads/search":
            return httpx.Response(200, json={"threads": [{"id": "thread/1"}]})
        if request.url.path == "/1/threads/thread/1":
            return httpx.Response(200, json={"thread": {"id": "thread/1"}})
        if request.url.path == "/1/messages/thread/1":
            return httpx.Response(200, json=[{"id": "message/1"}])
        if request.url.path == "/1/users/current":
            return httpx.Response(200, json={"private_folder_id": "folder/1", "shared_folder_ids": [], "group_folder_ids": []})
        if request.url.path == "/1/folders/":
            return httpx.Response(200, json={"folder/1": {"folder": {"id": "folder/1"}, "member_ids": []}})
        if request.url.path == "/1/folders/folder/1":
            return httpx.Response(200, json={"folder": {"id": "folder/1"}})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://quip/.*").mock(side_effect=handler)
    session = quip_session

    search = await _kb_tool(session, "quip", "read_search", {"query": "revenue", "limit": 200}, "agent-1")
    thread = await _kb_tool(session, "quip", "read_get_thread", {"thread_id": "thread/1"}, "agent-1")
    history = await _kb_tool(session, "quip", "read_get_thread_history", {"thread_id": "thread/1", "max_created_usec": 123}, "agent-1")
    folders = await _kb_tool(session, "quip", "read_list_folders", {}, "agent-1")
    folder = await _kb_tool(session, "quip", "read_get_folder", {"folder_id": "folder/1"}, "agent-1")
    messages = await _kb_tool(session, "quip", "read_get_messages", {"thread_id": "thread/1"}, "agent-1")

    assert search["threads"] == [{"id": "thread/1"}]
    assert thread["thread"]["id"] == "thread/1"
    assert history["messages"] == [{"id": "message/1"}]
    assert folders["folders"] == [{"id": "folder/1"}]
    assert folder["folder"]["id"] == "folder/1"
    assert messages["messages"] == [{"id": "message/1"}]
    assert any(url == "http://quip/1/threads/search?query=revenue&count=100" for _, url, _ in seen)
    assert any(url.startswith("http://quip/1/messages/thread%2F1?") and params["max_created_usec"] == "123" for _, url, params in seen)
    assert any(url == "http://quip/1/folders/?ids=folder%2F1" for _, url, _ in seen)


@respx.mock
@pytest.mark.asyncio
async def test_quip_writes_use_expected_payloads(quip_session: AsyncSession) -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        seen.append((request.method, str(request.url), body))
        if request.url.path == "/1/threads/new-document":
            return httpx.Response(200, json={"thread": {"id": "thread/1"}})
        if request.url.path == "/1/threads/edit-document":
            return httpx.Response(200, json={"thread": {"id": body["thread_id"]}})
        if request.url.path == "/1/messages/new":
            return httpx.Response(200, json={"message": {"id": "message/1"}})
        if request.url.path == "/1/threads/add-members":
            return httpx.Response(200, json={"thread_id": body["thread_id"]})
        if request.url.path == "/1/folders/new":
            return httpx.Response(200, json={"folder": {"id": "folder/1"}})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://quip/.*").mock(side_effect=handler)
    session = quip_session

    created = await _kb_tool(session, "quip", "write_create_thread", {"title": "Runbook", "body": "Body", "folder_ids": ["folder/1"]}, "agent-1")
    edited = await _kb_tool(session, "quip", "write_edit_thread", {"thread_id": "thread/1", "content": "New"}, "agent-1")
    message = await _kb_tool(session, "quip", "write_send_message", {"thread_id": "thread/1", "body": "Hello"}, "agent-1")
    shared = await _kb_tool(session, "quip", "write_share_thread", {"thread_id": "thread/1", "member_ids": ["user/1"]}, "agent-1")
    folder = await _kb_tool(session, "quip", "write_create_folder", {"name": "Team", "parent_id": "folder/parent", "member_ids": ["user/1"]}, "agent-1")

    assert created["thread"]["id"] == "thread/1"
    assert edited["thread"]["id"] == "thread/1"
    assert message["message"]["id"] == "message/1"
    assert shared["result"]["thread_id"] == "thread/1"
    assert folder["folder"]["id"] == "folder/1"
    assert any(url == "http://quip/1/threads/new-document" and body["member_ids"] == "folder/1" for _, url, body in seen)
    assert any(url == "http://quip/1/threads/edit-document" and body["format"] == "markdown" for _, url, body in seen)
    assert any(url == "http://quip/1/threads/add-members" and body["member_ids"] == "user/1" for _, url, body in seen)
