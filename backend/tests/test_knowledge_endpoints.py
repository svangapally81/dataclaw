from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select


@pytest.fixture
async def client(monkeypatch, tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'app.sqlite'}"
    demo_url = f"sqlite+aiosqlite:///{tmp_path / 'demo.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("DEMO_DATABASE_URL", demo_url)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("MASTER_KEY", "test-master-key-please-change")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-please-change")
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path / "wiki"))

    from app.core.config import get_settings

    get_settings.cache_clear()
    import app.db.session as session_module

    importlib.reload(session_module)
    from app import main as main_module

    importlib.reload(main_module)
    from app.services.vector_store import vector_store

    monkeypatch.setattr(vector_store, "_get_collection", lambda workspace_id: None)

    transport = ASGITransport(app=main_module.app)
    async with main_module.app.router.lifespan_context(main_module.app):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            login = await ac.post(
                "/auth/login",
                json={"email": "admin@dataclaw.local", "password": "dataclaw-local-admin"},
            )
            assert login.status_code == 200
            yield ac, main_module, Path(tmp_path) / "wiki"


@pytest.mark.asyncio
async def test_knowledge_pages_compile_and_graph_endpoints(client) -> None:
    ac, main_module, wiki_root = client
    from app.models.domain import WikiPage, Workspace
    from app.services.ingestion.summarizer import WikiPageDraft
    from app.services.ingestion.wiki_store import WikiStore

    async for db in main_module.get_session():
        workspace = await db.scalar(select(Workspace).limit(1))
        assert workspace is not None
        await WikiStore(root=wiki_root).upsert_page(
            db,
            WikiPageDraft(
                workspace_id=workspace.id,
                path="wiki/notion/data-glossary.md",
                tier=1,
                source_type="notion",
                source_id="p1",
                title="Data Glossary",
                body="Documents [[orders]] and [[customers]].",
                frontmatter={"title": "Data Glossary", "entities": ["orders", "customers"]},
                entities=["orders", "customers"],
                content_hash="hash",
            ),
        )
        await db.commit()
        break

    listed = await ac.get("/knowledge/pages")
    assert listed.status_code == 200
    assert any(page["path"] == "wiki/notion/data-glossary.md" for page in listed.json())

    page = await ac.get("/knowledge/pages/notion/data-glossary.md")
    assert page.status_code == 200
    assert page.json()["title"] == "Data Glossary"

    compile_response = await ac.post("/knowledge/compile")
    assert compile_response.status_code == 200
    assert compile_response.json()["nodes_created"] >= 2

    graph = await ac.get("/knowledge/graph?root=orders&depth=1")
    assert graph.status_code == 200
    assert any(node["canonical_name"] == "orders" for node in graph.json()["nodes"])

    async for db in main_module.get_session():
        assert await db.scalar(select(WikiPage).where(WikiPage.path == "wiki/notion/data-glossary.md"))
        break
