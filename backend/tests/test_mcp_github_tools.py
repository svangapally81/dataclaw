from __future__ import annotations

import base64
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
from app.services.mcp_executor import _github_tool


@pytest.fixture(scope="module")
async def github_session(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("github")
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
                slug="github",
                category="knowledge_base",
                display_name="GitHub",
                credential_state="configured",
                encrypted_credentials=encrypt_json(
                    get_settings().master_key,
                    {"base_url": "http://github", "token": "github-secret", "repositories": "acme/data.warehouse"},
                ),
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@respx.mock
@pytest.mark.asyncio
async def test_github_reads_use_expected_endpoints(
    github_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), dict(request.url.params), request.headers.get("Accept", "")))
        assert request.headers["Authorization"] == "Bearer github-secret"
        if request.url.path == "/repos/acme/data.warehouse/contents/docs/runbook.md":
            assert dict(request.url.params) == {}
            return httpx.Response(200, json={"path": "docs/runbook.md"})
        if request.url.path == "/repos/acme/data.warehouse/issues":
            return httpx.Response(200, json=[{"number": 1}, {"number": 2, "pull_request": {"url": "pr"}}])
        if request.url.path == "/repos/acme/data.warehouse/issues/1":
            return httpx.Response(200, json={"number": 1})
        if request.url.path == "/repos/acme/data.warehouse/pulls/2" and "diff" in request.headers.get("Accept", ""):
            return httpx.Response(200, text="diff --git a/file b/file")
        if request.url.path == "/repos/acme/data.warehouse/pulls/2":
            return httpx.Response(200, json={"number": 2})
        if request.url.path == "/repos/acme/data.warehouse/branches":
            return httpx.Response(200, json=[{"name": "main"}])
        if request.url.path == "/search/code":
            return httpx.Response(200, json={"total_count": 1, "items": [{"path": "README.md"}]})
        if request.url.path == "/repos/acme/data.warehouse/commits/abc123":
            return httpx.Response(200, json={"sha": "abc123"})
        if request.url.path == "/repos/acme/data.warehouse/actions/workflows":
            return httpx.Response(200, json={"total_count": 1, "workflows": [{"name": "CI"}]})
        if request.url.path == "/repos/acme/data.warehouse/actions/runs/99/logs":
            return httpx.Response(200, text="job log")
        if request.url.path == "/repos/acme/data.warehouse":
            return httpx.Response(200, json={"full_name": "acme/data.warehouse"})
        if request.url.path == "/repos/acme/data.warehouse/releases":
            return httpx.Response(200, json=[{"tag_name": "v1"}])
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://github/.*").mock(side_effect=handler)
    session = github_session

    file = await _github_tool(session, "read_get_file", {"repo": "acme/data.warehouse", "path": "docs/runbook.md"}, "agent-1")
    issues = await _github_tool(session, "read_list_issues", {"repo": "acme/data.warehouse", "state": "all", "limit": 200}, "agent-1")
    issue = await _github_tool(session, "read_get_issue", {"repo": "acme/data.warehouse", "number": 1}, "agent-1")
    pr = await _github_tool(session, "read_get_pr", {"repo": "acme/data.warehouse", "number": 2}, "agent-1")
    diff = await _github_tool(session, "read_get_pr_diff", {"repo": "acme/data.warehouse", "number": 2}, "agent-1")
    branches = await _github_tool(session, "read_list_branches", {"repo": "acme/data.warehouse"}, "agent-1")
    code = await _github_tool(session, "read_search_code", {"query": "customers", "repo": "acme/data.warehouse"}, "agent-1")
    commit = await _github_tool(session, "read_get_commit", {"repo": "acme/data.warehouse", "sha": "abc123"}, "agent-1")
    workflows = await _github_tool(session, "read_list_workflows", {"repo": "acme/data.warehouse"}, "agent-1")
    logs = await _github_tool(session, "read_get_workflow_run_logs", {"repo": "acme/data.warehouse", "run_id": "99"}, "agent-1")
    metadata = await _github_tool(session, "read_get_repo_metadata", {"repo": "acme/data.warehouse"}, "agent-1")
    releases = await _github_tool(session, "read_list_releases", {"repo": "acme/data.warehouse"}, "agent-1")

    assert file["file"]["path"] == "docs/runbook.md"
    assert issues["issues"] == [{"number": 1}]
    assert issue["issue"]["number"] == 1
    assert pr["pull_request"]["number"] == 2
    assert diff["diff"].startswith("diff --git")
    assert branches["branches"] == [{"name": "main"}]
    assert code["items"] == [{"path": "README.md"}]
    assert commit["commit"]["sha"] == "abc123"
    assert workflows["workflows"] == [{"name": "CI"}]
    assert logs["logs"] == "job log"
    assert metadata["repository"]["full_name"] == "acme/data.warehouse"
    assert releases["releases"] == [{"tag_name": "v1"}]
    assert any(
        url == "http://github/repos/acme/data.warehouse/issues?state=all&per_page=100"
        for _, url, _, _ in seen
    )
    assert any(
        url.startswith("http://github/search/code?")
        and params == {"q": "customers repo:acme/data.warehouse", "per_page": "30"}
        for _, url, params, _ in seen
    )


@respx.mock
@pytest.mark.asyncio
async def test_github_writes_use_expected_payloads(
    github_session: AsyncSession,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}")
        seen.append((request.method, str(request.url), body))
        if request.url.path.endswith("/contents/docs/runbook.md"):
            return httpx.Response(200, json={"commit": {"sha": "new"}})
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json={"number": 7, "state": "open"})
        if request.url.path.endswith("/issues") and request.method == "POST":
            return httpx.Response(200, json={"number": 8})
        if request.url.path.endswith("/issues/8/comments"):
            return httpx.Response(200, json={"id": 1})
        if request.url.path.endswith("/pulls/7/merge"):
            return httpx.Response(200, json={"merged": True})
        if request.url.path.endswith("/git/refs"):
            return httpx.Response(200, json={"ref": "refs/heads/dataclaw"})
        if request.url.path.endswith("/git/refs/heads/dataclaw") and request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path.endswith("/issues/7") and request.method == "PATCH":
            return httpx.Response(200, json={"number": 7, "state": "closed", "pull_request": {}})
        if request.url.path.endswith("/issues/8") and request.method == "PATCH":
            return httpx.Response(200, json={"number": 8, "state": "closed"})
        if request.url.path.endswith("/pulls/7/requested_reviewers"):
            return httpx.Response(200, json={"users": [{"login": "octo"}]})
        return httpx.Response(404, json={"path": request.url.path})

    respx.route(url__regex=r"http://github/.*").mock(side_effect=handler)
    session = github_session

    committed = await _github_tool(
        session,
        "write_commit_file",
        {"repo": "acme/data.warehouse", "path": "docs/runbook.md", "content": "hello", "message": "Update", "sha": "old"},
        "agent-1",
    )
    pr = await _github_tool(
        session,
        "write_create_pr",
        {"repo": "acme/data.warehouse", "title": "Update", "head": "dataclaw", "base": "main", "body": "Body"},
        "agent-1",
    )
    issue = await _github_tool(
        session,
        "write_create_issue",
        {"repo": "acme/data.warehouse", "title": "Bug", "body": "Fix", "labels": ["bug"]},
        "agent-1",
    )
    pr_comment = await _github_tool(session, "write_comment_on_pr", {"repo": "acme/data.warehouse", "number": 8, "body": "PR note"}, "agent-1")
    issue_comment = await _github_tool(session, "write_comment_on_issue", {"repo": "acme/data.warehouse", "number": 8, "body": "Issue note"}, "agent-1")
    merged = await _github_tool(session, "write_merge_pr", {"repo": "acme/data.warehouse", "number": 7, "method": "squash"}, "agent-1")
    branch = await _github_tool(session, "write_create_branch", {"repo": "acme/data.warehouse", "name": "dataclaw", "from_sha": "abc"}, "agent-1")
    deleted_branch = await _github_tool(session, "write_delete_branch", {"repo": "acme/data.warehouse", "name": "dataclaw"}, "agent-1")
    closed_pr = await _github_tool(session, "write_close_pr", {"repo": "acme/data.warehouse", "number": 7}, "agent-1")
    closed = await _github_tool(session, "write_close_issue", {"repo": "acme/data.warehouse", "number": 8}, "agent-1")
    review = await _github_tool(session, "write_request_review", {"repo": "acme/data.warehouse", "number": 7, "reviewers": ["octo"]}, "agent-1")

    assert committed["commit"]["commit"]["sha"] == "new"
    assert pr["pull_request"]["state"] == "open"
    assert issue["issue"]["number"] == 8
    assert pr_comment["comment"]["id"] == 1
    assert issue_comment["comment"]["id"] == 1
    assert merged["merge"]["merged"] is True
    assert branch["ref"]["ref"] == "refs/heads/dataclaw"
    assert deleted_branch["status"] == "deleted"
    assert closed_pr["pull_request"]["state"] == "closed"
    assert closed["issue"]["state"] == "closed"
    assert review["review_request"]["users"][0]["login"] == "octo"
    assert any(
        url == "http://github/repos/acme/data.warehouse/contents/docs/runbook.md"
        and body["content"] == base64.b64encode(b"hello").decode()
        and body["sha"] == "old"
        and "branch" not in body
        for _, url, body in seen
    )
    assert any(url == "http://github/repos/acme/data.warehouse/git/refs" and body == {"ref": "refs/heads/dataclaw", "sha": "abc"} for _, url, body in seen)
    assert any(url == "http://github/repos/acme/data.warehouse/pulls/7/requested_reviewers" and body == {"reviewers": ["octo"], "team_reviewers": []} for _, url, body in seen)
