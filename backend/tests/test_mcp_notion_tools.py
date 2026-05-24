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
from app.services.mcp_executor import _notion_tool


@pytest.fixture(scope="module")
async def notion_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("notion")
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
                slug="notion",
                category="knowledge_base",
                display_name="Notion",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"base_url": "http://notion", "integration_token": "notion-secret"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_notion_reads_use_expected_endpoints(
    notion_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), dict(request.url.params), body))
        assert request.headers["Authorization"] == "Bearer notion-secret"
        assert request.headers["Notion-Version"] == "2022-06-28"
        if request.url.path == "/v1/search":
            return httpx.Response(200, json={"results": [{"id": "page/1"}]})
        if request.url.path == "/v1/pages/page/1":
            return httpx.Response(200, json={"id": "page/1"})
        if request.url.path == "/v1/databases/db/1":
            return httpx.Response(200, json={"id": "db/1"})
        if request.url.path == "/v1/databases/db/1/query":
            return httpx.Response(200, json={"results": [{"id": "row/1"}], "has_more": False})
        if request.url.path == "/v1/blocks/block/1/children":
            return httpx.Response(200, json={"results": [{"id": "child/1"}]})
        if request.url.path == "/v1/comments":
            return httpx.Response(200, json={"results": [{"id": "comment/1"}]})
        if request.url.path == "/v1/users":
            return httpx.Response(200, json={"results": [{"id": "user/1"}]})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://notion/.*").mock(side_effect=handler)
    session = notion_session

    search = await _notion_tool(session, "read_search_pages", {"query": "orders", "page_size": 5}, "agent-1")
    page = await _notion_tool(session, "read_get_page", {"page_id": "page/1"}, "agent-1")
    database = await _notion_tool(session, "read_get_database", {"database_id": "db/1"}, "agent-1")
    rows = await _notion_tool(
        session,
        "read_query_database",
        {
            "database_id": "db/1",
            "filter": {"property": "Status", "select": {"equals": "Open"}},
            "start_cursor": "cursor/1",
        },
        "agent-1",
    )
    children = await _notion_tool(
        session,
        "read_get_block_children",
        {"block_id": "block/1", "page_size": 100, "start_cursor": "cursor/1"},
        "agent-1",
    )
    comments = await _notion_tool(session, "read_get_comments", {"page_id": "page/1"}, "agent-1")
    users = await _notion_tool(session, "read_list_users", {}, "agent-1")

    assert search["pages"] == [{"id": "page/1"}]
    assert page["page"]["id"] == "page/1"
    assert database["database"]["id"] == "db/1"
    assert rows["results"] == [{"id": "row/1"}]
    assert children["children"] == [{"id": "child/1"}]
    assert comments["comments"] == [{"id": "comment/1"}]
    assert users["users"] == [{"id": "user/1"}]
    assert any(
        url == "http://notion/v1/search" and body == {"query": "orders", "page_size": 5}
        for _, url, _, body in seen
    )
    assert any(
        url == "http://notion/v1/databases/db%2F1/query"
        and body["page_size"] == 10
        and body["start_cursor"] == "cursor/1"
        for _, url, _, body in seen
    )
    assert any(
        url.startswith("http://notion/v1/blocks/block%2F1/children?")
        and params == {"page_size": "100", "start_cursor": "cursor/1"}
        for _, url, params, _ in seen
    )
    assert any(url.startswith("http://notion/v1/comments?") and params["block_id"] == "page/1" for _, url, params, _ in seen)


@respx.mock
@pytest.mark.asyncio
async def test_notion_writes_use_expected_payloads(
    notion_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if request.url.path == "/v1/pages":
            return httpx.Response(200, json={"id": "page/1"})
        if request.url.path == "/v1/blocks/page/1/children":
            return httpx.Response(200, json={"results": [{"id": "block/1"}]})
        if request.url.path == "/v1/pages/page/1":
            return httpx.Response(200, json={"id": "page/1", "archived": body.get("archived", False)})
        if request.url.path == "/v1/comments":
            return httpx.Response(200, json={"id": "comment/1"})
        if request.url.path == "/v1/databases":
            return httpx.Response(200, json={"id": "db/1"})
        if request.url.path == "/v1/blocks/block/1":
            return httpx.Response(200, json={"id": "block/1"})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://notion/.*").mock(side_effect=handler)
    session = notion_session

    created = await _notion_tool(session, "write_create_page", {"parent_id": "parent/1", "title": "Runbook", "body": "Body"}, "agent-1")
    appended = await _notion_tool(session, "write_append_to_page", {"page_id": "page/1", "body": "More"}, "agent-1")
    updated = await _notion_tool(
        session,
        "write_update_page_properties",
        {"page_id": "page/1", "properties": {"Status": {"select": {"name": "Done"}}}},
        "agent-1",
    )
    archived = await _notion_tool(session, "write_archive_page", {"page_id": "page/1"}, "agent-1")
    comment = await _notion_tool(session, "write_create_comment", {"page_id": "page/1", "body": "Looks good"}, "agent-1")
    database = await _notion_tool(
        session,
        "write_create_database",
        {"parent_page_id": "page/1", "title": "Tasks", "properties": {"Name": {"title": {}}}},
        "agent-1",
    )
    block = await _notion_tool(
        session,
        "write_update_block",
        {"block_id": "block/1", "type": "paragraph", "content": {"rich_text": [{"text": {"content": "Updated"}}]}},
        "agent-1",
    )

    assert created["page"]["id"] == "page/1"
    assert appended["result"]["results"][0]["id"] == "block/1"
    assert updated["page"]["id"] == "page/1"
    assert archived["page"]["archived"] is True
    assert comment["comment"]["id"] == "comment/1"
    assert database["database"]["id"] == "db/1"
    assert block["block"]["id"] == "block/1"
    assert any(
        url == "http://notion/v1/pages"
        and body["parent"] == {"type": "page_id", "page_id": "parent/1"}
        and body["properties"]["title"]["title"][0]["text"]["content"] == "Runbook"
        for _, url, body in seen
    )
    assert any(url == "http://notion/v1/pages/page%2F1" and body == {"archived": True} for _, url, body in seen)
    assert any(url == "http://notion/v1/comments" and body["parent"] == {"page_id": "page/1"} for _, url, body in seen)
    assert any(url == "http://notion/v1/databases" and body["title"][0]["text"]["content"] == "Tasks" for _, url, body in seen)
    assert any(url == "http://notion/v1/blocks/block%2F1" and body == {"paragraph": {"rich_text": [{"text": {"content": "Updated"}}]}} for _, url, body in seen)
