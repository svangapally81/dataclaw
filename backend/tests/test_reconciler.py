from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import WikiPage, Workspace
from app.services.ingestion.reconciler import reconcile_wiki_disk_edits
from app.services.ingestion.summarizer import WikiPageDraft
from app.services.ingestion.wiki_store import WikiStore


@pytest.fixture
async def session(tmp_path, monkeypatch):
    import app.services.ingestion.wiki_store as wiki_store_module

    active_vector_store = wiki_store_module.vector_store
    monkeypatch.setenv("WIKI_ROOT", str(tmp_path / "wiki"))
    monkeypatch.setattr(active_vector_store, "_get_collection", lambda workspace_id: None)
    active_vector_store._test_double[active_vector_store._collection_name("ws1")] = {}
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        db.add(Workspace(id="ws1", name="Test"))
        await db.commit()
        yield db, tmp_path, active_vector_store
    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciler_refreshes_sqlite_and_vectors_from_disk(session) -> None:
    db, tmp_path, active_vector_store = session
    store = WikiStore(root=Path(tmp_path) / "wiki")
    page = await store.upsert_page(
        db,
        WikiPageDraft(
            workspace_id="ws1",
            path="wiki/notion/data-glossary.md",
            tier=1,
            source_type="notion",
            source_id="p1",
            title="Data Glossary",
            body="# Data Glossary\n\nOld body.",
            frontmatter={"title": "Data Glossary", "entities": ["orders"]},
            entities=["orders"],
            content_hash="old",
        ),
    )
    await db.commit()

    disk_path = Path(page.disk_path)
    disk_path.write_text(
        "---\ntitle: \"Data Glossary\"\nentities:\n  - \"customers\"\n---\n\n# Data Glossary\n\nNew body.",
        encoding="utf-8",
    )
    changed = await reconcile_wiki_disk_edits(db, "ws1")

    refreshed = await db.scalar(select(WikiPage).where(WikiPage.id == page.id))
    bucket = active_vector_store._test_double[active_vector_store._collection_name("ws1")]
    assert changed == 1
    assert refreshed is not None
    assert refreshed.entities == ["customers"]
    assert "New body" in refreshed.body
    assert any(item[1]["asset_type"] == "wiki_page" for item in bucket.values())
