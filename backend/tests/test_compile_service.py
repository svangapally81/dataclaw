import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import ColumnLineageEdge, KnowledgeEdge, KnowledgeNode, WikiPage, Workspace
from app.services.agents.chat import _column_lineage_context
from app.services.knowledge_compile.service import CompileService
from app.services.retrieval import BrainRetriever
from app.services.vector_store import vector_store


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        db.add(Workspace(id="ws1", name="Test"))
        db.add_all(
            [
                WikiPage(
                    workspace_id="ws1",
                    path="wiki/notion/data-glossary.md",
                    disk_path="/tmp/data-glossary.md",
                    tier=1,
                    source_type="notion",
                    source_id="p1",
                    title="Data glossary",
                    body="Documents [[orders]], [[customers]], and [[lifetime_value]].",
                    frontmatter={"entities": ["orders", "customers", "lifetime_value"]},
                    entities=["orders", "customers", "lifetime_value"],
                    content_hash="a",
                ),
                WikiPage(
                    workspace_id="ws1",
                    path="wiki/airflow/daily_orders_refresh.md",
                    disk_path="/tmp/daily_orders_refresh.md",
                    tier=1,
                    source_type="airflow",
                    source_id="daily_orders_refresh",
                    title="daily_orders_refresh",
                    body="Loads orders.",
                    frontmatter={"produces": ["postgres/orders"]},
                    entities=[],
                    content_hash="b",
                ),
                WikiPage(
                    workspace_id="ws1",
                    path="wiki/postgres/orders.md",
                    disk_path="/tmp/orders.md",
                    tier=1,
                    source_type="postgres",
                    source_id="orders",
                    title="orders",
                    body="customer_id references customers. orders.revenue derives from payments.amount.",
                    frontmatter={
                        "entities": ["orders"],
                        "column_lineage": [
                            {
                                "source": "postgres/payments.amount",
                                "target": "postgres/orders.revenue",
                                "relationship": "derives_from",
                            }
                        ],
                    },
                    entities=["orders"],
                    content_hash="c",
                ),
            ]
        )
        await db.commit()
        yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_compile_service_creates_nodes_edges_and_is_idempotent(session: AsyncSession) -> None:
    first = await CompileService(session).compile("ws1")
    nodes = list((await session.scalars(select(KnowledgeNode))).all())
    edges = list((await session.scalars(select(KnowledgeEdge))).all())

    assert {"orders", "customers", "lifetime_value", "daily_orders_refresh"}.issubset(
        {node.canonical_name for node in nodes}
    )
    assert any(edge.relationship == "produces" for edge in edges)
    assert any(edge.relationship == "references_fk" for edge in edges)
    column_edges = list((await session.scalars(select(ColumnLineageEdge))).all())
    assert any(edge.target_table == "orders" and edge.target_column == "revenue" for edge in column_edges)
    assert all(node.connector_slug for node in nodes)
    assert all(node.summary for node in nodes)
    assert all(node.summary_embedded_at is not None for node in nodes)
    assert first.edges_created >= 3

    second = await CompileService(session).compile("ws1")
    assert second.nodes_created == 0
    assert second.edges_created == 0
    assert len(list((await session.scalars(select(KnowledgeNode))).all())) == len(nodes)
    assert len(list((await session.scalars(select(KnowledgeEdge))).all())) == len(edges)


@pytest.mark.asyncio
async def test_compile_incremental_touches_only_dirty_page_edges(session: AsyncSession) -> None:
    await CompileService(session).compile("ws1")
    before_edges = list((await session.scalars(select(KnowledgeEdge))).all())
    edge_runs_before = {edge.id: edge.compile_run_id for edge in before_edges}
    page = await session.scalar(
        select(WikiPage).where(WikiPage.path == "wiki/notion/data-glossary.md")
    )
    assert page is not None
    page.body = "Documents [[orders]], [[customers]], [[gross_revenue]], and [[lifetime_value]]."
    page.entities = ["orders", "customers", "lifetime_value", "gross_revenue"]
    page.frontmatter = {"entities": ["orders", "customers", "lifetime_value", "gross_revenue"]}
    await session.commit()

    result = await CompileService(session).compile_incremental("ws1", [page.path])
    after_edges = list((await session.scalars(select(KnowledgeEdge))).all())
    after_nodes = list((await session.scalars(select(KnowledgeNode))).all())
    dirty_doc = next(node for node in after_nodes if node.canonical_name == "data_glossary")

    assert result.nodes_created >= 1
    assert any(node.canonical_name == "gross_revenue" for node in after_nodes)
    assert any(edge.src_node_id == dirty_doc.id and edge.id not in edge_runs_before for edge in after_edges)
    assert all(
        edge.compile_run_id == edge_runs_before[edge.id]
        for edge in after_edges
        if edge.id in edge_runs_before and edge.src_node_id != dirty_doc.id
    )


@pytest.mark.asyncio
async def test_compile_resets_vector_collection_when_embedding_model_changes(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None, str | None, str | None]] = []

    def fake_ensure(
        workspace_id: str,
        embedding_model: str | None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        calls.append((workspace_id, embedding_model, api_key, base_url))

    async def fake_resolve(_session: AsyncSession):
        return "ollama-local", "llama3.1:8b", "http://localhost:11434/v1", "nomic-embed-text"

    monkeypatch.setattr(vector_store, "ensure_embedding_model", fake_ensure)
    monkeypatch.setattr("app.services.knowledge_compile.service.resolve_openai", fake_resolve)

    await CompileService(session).compile("ws1")

    assert calls == [("ws1", "nomic-embed-text", "ollama-local", "http://localhost:11434/v1")]


@pytest.mark.asyncio
async def test_compile_keeps_same_entity_distinct_per_connector(session: AsyncSession) -> None:
    session.add(
        WikiPage(
            workspace_id="ws1",
            path="wiki/snowflake/orders.md",
            disk_path="/tmp/snowflake-orders.md",
            tier=1,
            source_type="snowflake",
            source_id="orders",
            title="orders",
            body="Snowflake orders table.",
            frontmatter={"entities": ["orders"]},
            entities=["orders"],
            content_hash="snowflake-orders",
        )
    )
    await session.commit()

    await CompileService(session).compile("ws1")
    rows = list(
        (
            await session.scalars(
                select(KnowledgeNode).where(
                    KnowledgeNode.canonical_name == "orders",
                    KnowledgeNode.type == "table",
                )
            )
        ).all()
    )

    assert {node.connector_slug for node in rows} >= {"postgres", "snowflake"}


@pytest.mark.asyncio
async def test_brain_retriever_returns_source_scoped_nodes_and_chunks(session: AsyncSession) -> None:
    await CompileService(session).compile("ws1")

    result = await BrainRetriever(session).retrieve("ws1", "what feeds orders?", connector_slugs=["postgres"])

    assert result.nodes
    assert all(node.connector_slug == "postgres" for node in result.nodes)
    assert result.trace["candidate_node_ids"]
    assert result.trace["connector_slugs"] == ["postgres"]


@pytest.mark.asyncio
async def test_column_lineage_context_mentions_column_edges(session: AsyncSession) -> None:
    await CompileService(session).compile("ws1")

    context = await _column_lineage_context(session, "ws1", "what feeds orders.revenue?")

    assert context
    assert "payments.amount" in context[0]
    assert "orders.revenue" in context[0]
