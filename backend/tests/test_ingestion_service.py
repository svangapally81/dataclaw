from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import WikiPage, Workspace
from app.services.ingestion.service import IngestionService
from app.services.ingestion.summarizer import WikiPageDraft, content_hash
from app.services.ingestion.wiki_store import WikiStore


@pytest.fixture
async def session(tmp_path, monkeypatch):
    import app.services.ingestion.service as ingestion_service_module
    import app.services.ingestion.wiki_store as wiki_store_module

    active_vector_store = ingestion_service_module.vector_store
    monkeypatch.setattr(wiki_store_module, "vector_store", active_vector_store)
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
async def test_ingestion_service_writes_wiki_disk_sqlite_and_vectors(session) -> None:
    db, tmp_path, active_vector_store = session
    store = WikiStore(root=Path(tmp_path) / "wiki")
    result = await IngestionService(db, store).ingest_payload(
        "ws1",
        "notion",
        {
            "pages": [
                {"id": "p1", "title": "Data Glossary", "body": "The [[orders]] table joins [[customers]]."},
                {"id": "p2", "title": "Ownership Runbook", "body": "Analytics owns orders."},
            ]
        },
    )
    await db.commit()

    pages = list((await db.scalars(select(WikiPage).order_by(WikiPage.path))).all())
    assert result.artifacts_processed == 2
    assert len(pages) == 3
    assert (Path(tmp_path) / "wiki" / "ws1" / "notion" / "data-glossary.md").exists()
    assert any(page.path == "wiki/notion/index.md" for page in pages)
    bucket = active_vector_store._test_double[active_vector_store._collection_name("ws1")]
    assert any(item[1]["asset_type"] == "wiki_page" for item in bucket.values())
    assert any(item[1]["asset_type"] == "raw_chunk" for item in bucket.values())


@pytest.mark.asyncio
async def test_ingestion_service_skips_per_artifact_llm_calls_for_ollama(session, monkeypatch) -> None:
    db, tmp_path, _active_vector_store = session
    captured_configs = []

    async def fake_summarize_artifact(**kwargs):
        captured_configs.append(kwargs["openai_config"])
        content = kwargs["content"]
        title = content["title"]
        return WikiPageDraft(
            workspace_id=kwargs["workspace_id"],
            path="wiki/notion/local-fast-path.md",
            tier=1,
            source_type=kwargs["source_type"],
            source_id=kwargs["source_id"],
            title=title,
            body=f"# {title}\n",
            frontmatter={
                "title": title,
                "source_type": kwargs["source_type"],
                "source_id": kwargs["source_id"],
                "entities": [],
                "last_content_hash": content_hash(content),
            },
            entities=[],
            content_hash=content_hash(content),
        )

    async def fake_resolve_openai(_session):
        return (None, None, None, None)

    monkeypatch.setattr("app.services.ingestion.service.summarize_artifact", fake_summarize_artifact)
    monkeypatch.setattr(
        "app.services.ingestion.service.resolve_openai",
        fake_resolve_openai,
    )

    store = WikiStore(root=Path(tmp_path) / "wiki")
    result = await IngestionService(db, store).ingest_payload(
        "ws1",
        "notion",
        {"pages": [{"id": "p1", "title": "Local Fast Path", "body": "The [[orders]] table."}]},
    )

    assert result.artifacts_processed == 1
    assert captured_configs == [(None, None, None, None)]
