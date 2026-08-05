from __future__ import annotations

import json
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
async def confluence_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("confluence")
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
                slug="confluence",
                category="knowledge_base",
                display_name="Confluence",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"site_url": "http://confluence", "email": "a@example.com", "api_token": "conf-secret"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_confluence_reads_use_expected_endpoints(confluence_session: AsyncSession) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), dict(request.url.params)))
        assert request.headers["Authorization"].startswith("Basic ")
        if request.url.path == "/wiki/rest/api/search":
            return httpx.Response(200, json={"results": [{"id": "page/1"}]})
        if request.url.path == "/wiki/rest/api/content/page/1":
            return httpx.Response(200, json={"id": "page/1"})
        if request.url.path == "/wiki/rest/api/content/page/1/child/page":
            return httpx.Response(200, json={"results": [{"id": "child/1"}]})
        if request.url.path == "/wiki/rest/api/space/ENG":
            return httpx.Response(200, json={"key": "ENG"})
        if request.url.path == "/wiki/rest/api/content/page/1/history":
            return httpx.Response(200, json={"latest": True})
        if request.url.path == "/wiki/rest/api/content/page/1/child/comment":
            return httpx.Response(200, json={"results": [{"id": "comment/1"}]})
        if request.url.path == "/wiki/rest/api/space":
            return httpx.Response(200, json={"results": [{"key": "ENG"}]})
        if request.url.path == "/wiki/rest/api/content/page/1/label":
            return httpx.Response(200, json={"results": [{"name": "runbook"}]})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://confluence/.*").mock(side_effect=handler)
    session = confluence_session

    pages = await _kb_tool(session, "confluence", "read_search_pages", {"query": 'revenue "north"'}, "agent-1")
    page = await _kb_tool(session, "confluence", "read_get_page", {"page_id": "page/1"}, "agent-1")
    children = await _kb_tool(session, "confluence", "read_get_page_children", {"page_id": "page/1"}, "agent-1")
    space = await _kb_tool(session, "confluence", "read_get_space", {"space_key": "ENG"}, "agent-1")
    history = await _kb_tool(session, "confluence", "read_get_page_history", {"page_id": "page/1"}, "agent-1")
    attachments = await _kb_tool(session, "confluence", "read_search_attachments", {"query": "csv"}, "agent-1")
    comments = await _kb_tool(session, "confluence", "read_get_comments", {"page_id": "page/1"}, "agent-1")
    spaces = await _kb_tool(session, "confluence", "read_list_spaces", {}, "agent-1")
    labels = await _kb_tool(session, "confluence", "read_get_labels", {"page_id": "page/1"}, "agent-1")

    assert pages["pages"] == [{"id": "page/1"}]
    assert page["page"]["id"] == "page/1"
    assert children["children"] == [{"id": "child/1"}]
    assert space["space"]["key"] == "ENG"
    assert history["history"]["latest"] is True
    assert attachments["attachments"] == [{"id": "page/1"}]
    assert comments["comments"] == [{"id": "comment/1"}]
    assert spaces["spaces"] == [{"key": "ENG"}]
    assert labels["labels"] == [{"name": "runbook"}]
    assert any(params.get("cql") == 'type=page and text ~ "revenue \\"north\\""' for _, _, params in seen)
    assert any(params.get("cql") == 'type=attachment and text ~ "csv"' for _, _, params in seen)


@respx.mock
@pytest.mark.asyncio
async def test_confluence_writes_use_expected_payloads(confluence_session: AsyncSession) -> None:
    seen: list[tuple[str, str, dict | str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/child/attachment"):
            body: dict | str = request.content.decode(errors="replace")
        else:
            body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if request.url.path == "/wiki/rest/api/content" and request.method == "POST" and body.get("type") == "page":
            return httpx.Response(200, json={"id": "page/1"})
        if request.url.path == "/wiki/rest/api/content/page/1" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "page/1",
                    "title": "Runbook",
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>Body</p>"}},
                },
            )
        if request.url.path == "/wiki/rest/api/content/page/1" and request.method == "PUT":
            return httpx.Response(200, json={"id": "page/1", "title": body["title"]})
        if request.url.path == "/wiki/rest/api/content/page/1/label":
            return httpx.Response(200, json={"results": [{"name": "runbook"}]})
        if request.url.path == "/wiki/rest/api/content" and request.method == "POST" and body.get("type") == "comment":
            return httpx.Response(200, json={"id": "comment/1"})
        if request.url.path == "/wiki/rest/api/content/page/1/child/attachment":
            assert request.headers["X-Atlassian-Token"] == "no-check"
            return httpx.Response(200, json={"results": [{"id": "attachment/1"}]})
        if request.url.path == "/wiki/rest/api/content/page/1/move/append/parent/1":
            return httpx.Response(200, json={"id": "page/1"})
        if request.url.path == "/wiki/rest/api/content/page/1" and request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://confluence/.*").mock(side_effect=handler)
    session = confluence_session

    created = await _kb_tool(session, "confluence", "write_create_page", {"space_key": "ENG", "title": "Runbook", "body": "<p>Body</p>", "parent_id": "parent/1"}, "agent-1")
    appended = await _kb_tool(session, "confluence", "write_append_to_page", {"page_id": "page/1", "body": "<p>More</p>"}, "agent-1")
    updated = await _kb_tool(session, "confluence", "write_update_page", {"page_id": "page/1", "title": "Runbook 2", "content": "<p>New</p>", "version": 2}, "agent-1")
    labels = await _kb_tool(session, "confluence", "write_add_label", {"page_id": "page/1", "label": "runbook"}, "agent-1")
    comment = await _kb_tool(session, "confluence", "write_create_comment", {"page_id": "page/1", "body": "<p>Comment</p>"}, "agent-1")
    attachment = await _kb_tool(
        session,
        "confluence",
        "write_create_attachment",
        {"page_id": "page/1", "filename": "a.txt", "content": "aGVsbG8=", "content_encoding": "base64"},
        "agent-1",
    )
    moved = await _kb_tool(session, "confluence", "write_move_page", {"page_id": "page/1", "parent_id": "parent/1"}, "agent-1")
    deleted = await _kb_tool(session, "confluence", "write_delete_page", {"page_id": "page/1"}, "agent-1")

    assert created["page"]["id"] == "page/1"
    assert appended["page"]["title"] == "Runbook"
    assert updated["page"]["title"] == "Runbook 2"
    assert labels["labels"] == [{"name": "runbook"}]
    assert comment["comment"]["id"] == "comment/1"
    assert attachment["attachment"]["results"][0]["id"] == "attachment/1"
    assert moved["page"]["id"] == "page/1"
    assert deleted["status"] == "deleted"
    assert any(url == "http://confluence/wiki/rest/api/content" and body["space"] == {"key": "ENG"} for _, url, body in seen if isinstance(body, dict))
    assert any(
        url.startswith("http://confluence/wiki/rest/api/content/page")
        and isinstance(body, dict)
        and body.get("version") == {"number": 2}
        for method, url, body in seen
        if method == "PUT"
    )
    assert any(url == "http://confluence/wiki/rest/api/content/page%2F1/move/append/parent%2F1" for _, url, _ in seen)
