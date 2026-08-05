from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import encrypt_json
from app.db.base import Base
from app.models.domain import Connector, Workspace
from app.services import mcp_executor


@pytest.fixture(scope="module")
async def google_docs_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("google-docs")
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
                slug="google_docs",
                category="knowledge_base",
                display_name="Google Docs",
                credential_state="configured",
                encrypted_credentials=encrypt_json(get_settings().master_key, {"service_account_json": {"client_email": "test@example.com"}}),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


class FakeCall:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeFiles:
    def __init__(self, calls):
        self.calls = calls

    def list(self, **kwargs):
        self.calls.append(("files.list", kwargs))
        return FakeCall({"files": [{"id": "doc-1", "name": "Revenue"}]})

    def get(self, **kwargs):
        self.calls.append(("files.get", kwargs))
        return FakeCall({"id": kwargs["fileId"], "name": "Revenue", "parents": ["old-folder"]})

    def update(self, **kwargs):
        self.calls.append(("files.update", kwargs))
        return FakeCall({"id": kwargs["fileId"], "name": kwargs.get("body", {}).get("name", "Revenue"), "parents": [kwargs.get("addParents", "new-folder")]})


class FakeComments:
    def __init__(self, calls):
        self.calls = calls

    def list(self, **kwargs):
        self.calls.append(("comments.list", kwargs))
        return FakeCall({"comments": [{"id": "comment-1"}]})

    def create(self, **kwargs):
        self.calls.append(("comments.create", kwargs))
        return FakeCall({"id": "comment-1", "content": kwargs["body"]["content"]})


class FakeRevisions:
    def __init__(self, calls):
        self.calls = calls

    def list(self, **kwargs):
        self.calls.append(("revisions.list", kwargs))
        return FakeCall({"revisions": [{"id": "rev-1"}]})


class FakePermissions:
    def __init__(self, calls):
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(("permissions.create", kwargs))
        return FakeCall({"id": "permission-1"})


class FakeDrive:
    def __init__(self, calls):
        self._files = FakeFiles(calls)
        self._comments = FakeComments(calls)
        self._revisions = FakeRevisions(calls)
        self._permissions = FakePermissions(calls)

    def files(self):
        return self._files

    def comments(self):
        return self._comments

    def revisions(self):
        return self._revisions

    def permissions(self):
        return self._permissions


class FakeDocuments:
    def __init__(self, calls):
        self.calls = calls

    def get(self, **kwargs):
        self.calls.append(("documents.get", kwargs))
        return FakeCall(
            {
                "documentId": kwargs["documentId"],
                "title": "Revenue",
                "body": {"content": [{"endIndex": 8, "paragraph": {"elements": [{"textRun": {"content": "Hello"}}]}}]},
            }
        )

    def create(self, **kwargs):
        self.calls.append(("documents.create", kwargs))
        return FakeCall({"documentId": "doc-new", "title": kwargs["body"]["title"]})

    def batchUpdate(self, **kwargs):
        self.calls.append(("documents.batchUpdate", kwargs))
        return FakeCall({"documentId": kwargs["documentId"], "replies": []})


class FakeDocs:
    def __init__(self, calls):
        self._documents = FakeDocuments(calls)

    def documents(self):
        return self._documents


class FakeGoogleAdapter:
    def __init__(self, calls):
        self.calls = calls

    def _services(self, credentials):
        return FakeDrive(self.calls), FakeDocs(self.calls)


@pytest.fixture
def fake_google(monkeypatch):
    calls = []
    original = mcp_executor.adapter_for

    def adapter_for(slug: str):
        if slug == "google_docs":
            return FakeGoogleAdapter(calls)
        return original(slug)

    monkeypatch.setattr(mcp_executor, "adapter_for", adapter_for)
    return calls


@pytest.mark.asyncio
async def test_google_docs_reads_use_drive_and_docs_services(google_docs_session: AsyncSession, fake_google) -> None:
    session = google_docs_session

    docs = await mcp_executor._kb_tool(session, "google_docs", "read_list_docs", {"limit": 2}, "agent-1")
    search = await mcp_executor._kb_tool(session, "google_docs", "read_search_docs", {"query": "Revenue"}, "agent-1")
    doc = await mcp_executor._kb_tool(session, "google_docs", "read_get_doc", {"doc_id": "doc-1"}, "agent-1")
    comments = await mcp_executor._kb_tool(session, "google_docs", "read_get_doc_comments", {"doc_id": "doc-1"}, "agent-1")
    revisions = await mcp_executor._kb_tool(session, "google_docs", "read_get_doc_revisions", {"doc_id": "doc-1"}, "agent-1")
    folder = await mcp_executor._kb_tool(session, "google_docs", "read_list_folder_contents", {"folder_id": "folder-1"}, "agent-1")
    shared = await mcp_executor._kb_tool(session, "google_docs", "read_list_shared_with_me", {}, "agent-1")
    metadata = await mcp_executor._kb_tool(session, "google_docs", "read_get_doc_metadata", {"doc_id": "doc-1"}, "agent-1")

    assert docs["docs"] == [{"id": "doc-1", "name": "Revenue"}]
    assert search["docs"] == [{"id": "doc-1", "name": "Revenue"}]
    assert doc["doc"]["body_text"] == "Hello"
    assert comments["comments"] == [{"id": "comment-1"}]
    assert revisions["revisions"] == [{"id": "rev-1"}]
    assert folder["files"] == [{"id": "doc-1", "name": "Revenue"}]
    assert shared["files"] == [{"id": "doc-1", "name": "Revenue"}]
    assert metadata["metadata"]["id"] == "doc-1"
    assert ("documents.get", {"documentId": "doc-1"}) in fake_google
    assert any(name == "files.list" and "name contains 'Revenue'" in kwargs["q"] for name, kwargs in fake_google)
    assert any(name == "files.list" and kwargs["q"] == "'folder-1' in parents and trashed=false" for name, kwargs in fake_google)
    assert any(
        name == "comments.list"
        and kwargs["fields"] == "nextPageToken, comments(id, content, author, createdTime, modifiedTime, resolved, replies)"
        for name, kwargs in fake_google
    )
    assert any(
        name == "revisions.list"
        and kwargs["fields"] == "nextPageToken, revisions(id, modifiedTime, lastModifyingUser, size, keepForever)"
        for name, kwargs in fake_google
    )


@pytest.mark.asyncio
async def test_google_docs_writes_use_drive_and_docs_services(google_docs_session: AsyncSession, fake_google) -> None:
    session = google_docs_session

    created = await mcp_executor._kb_tool(session, "google_docs", "write_create_doc", {"title": "Runbook", "body": "Body"}, "agent-1")
    appended = await mcp_executor._kb_tool(session, "google_docs", "write_append_to_doc", {"doc_id": "doc-1", "content": "More"}, "agent-1")
    replaced = await mcp_executor._kb_tool(
        session,
        "google_docs",
        "write_replace_text",
        {"doc_id": "doc-1", "find": "old", "replace": "new"},
        "agent-1",
    )
    comment = await mcp_executor._kb_tool(session, "google_docs", "write_create_comment", {"doc_id": "doc-1", "body": "Looks good"}, "agent-1")
    shared = await mcp_executor._kb_tool(session, "google_docs", "write_share_doc", {"doc_id": "doc-1", "email": "a@example.com", "role": "reader"}, "agent-1")
    moved = await mcp_executor._kb_tool(session, "google_docs", "write_move_doc", {"doc_id": "doc-1", "folder_id": "folder-2"}, "agent-1")
    renamed = await mcp_executor._kb_tool(session, "google_docs", "write_rename_doc", {"doc_id": "doc-1", "name": "New name"}, "agent-1")

    assert created["doc"]["documentId"] == "doc-new"
    assert appended["status"] == "updated"
    assert replaced["result"]["documentId"] == "doc-1"
    assert comment["comment"]["content"] == "Looks good"
    assert shared["permission"]["id"] == "permission-1"
    assert moved["file"]["parents"] == ["folder-2"]
    assert renamed["file"]["name"] == "New name"
    assert any(name == "documents.batchUpdate" and kwargs["documentId"] == "doc-new" for name, kwargs in fake_google)
    assert any(
        name == "documents.batchUpdate"
        and kwargs["body"]["requests"][0].get("replaceAllText", {}).get("replaceText") == "new"
        for name, kwargs in fake_google
    )
    assert any(name == "permissions.create" and kwargs["body"]["emailAddress"] == "a@example.com" for name, kwargs in fake_google)
    assert any(name == "files.update" and kwargs.get("removeParents") == "old-folder" for name, kwargs in fake_google)
