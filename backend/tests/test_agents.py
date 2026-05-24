from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import (
    Alert,
    Dataset,
    LineageEdge,
    TableAsset,
    User,
    Workspace,
)
from app.services.agents.docs_agent import run_docs_agent
from app.services.agents.freshness_agent import run_freshness_agent
from app.services.agents.lineage_agent import run_lineage_agent


@pytest.fixture
async def session(tmp_path):
    db_path = tmp_path / "test.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        workspace = Workspace(name="Test")
        user = User(email="t@test.local", password_hash="x")
        session.add_all([workspace, user])
        await session.flush()
        dataset = Dataset(workspace_id=workspace.id, name="test", source_type="sqlite", schema_name="main")
        session.add(dataset)
        await session.flush()
        session.add_all(
            [
                TableAsset(
                    dataset_id=dataset.id,
                    name="customers",
                    columns=[{"name": "customer_id", "type": "text", "description": ""}],
                    row_count=3,
                ),
                TableAsset(
                    dataset_id=dataset.id,
                    name="orders",
                    columns=[
                        {"name": "order_id", "type": "text", "description": ""},
                        {"name": "customer_id", "type": "text", "description": ""},
                        {"name": "net_revenue", "type": "real", "description": ""},
                    ],
                    row_count=4,
                ),
                TableAsset(
                    dataset_id=dataset.id,
                    name="empty_table",
                    columns=[{"name": "id", "type": "text", "description": ""}],
                    row_count=0,
                ),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_lineage_agent_finds_fk_match(session: AsyncSession) -> None:
    run = await run_lineage_agent(session)
    edges = list((await session.scalars(select(LineageEdge))).all())
    assert run.status == "completed"
    assert any(e.source_table == "orders" and e.target_table == "customers" for e in edges)


@pytest.mark.asyncio
async def test_lineage_agent_idempotent(session: AsyncSession) -> None:
    await run_lineage_agent(session)
    await run_lineage_agent(session)
    edges = list((await session.scalars(select(LineageEdge))).all())
    matches = [e for e in edges if e.source_table == "orders" and e.target_table == "customers"]
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_freshness_agent_flags_empty_table(session: AsyncSession) -> None:
    run = await run_freshness_agent(session)
    alerts = list((await session.scalars(select(Alert))).all())
    assert run.status == "completed"
    assert any(alert.title == "Freshness: empty_table" and alert.severity == "critical" for alert in alerts)


@pytest.mark.asyncio
async def test_freshness_agent_flags_stagnant_after_second_run(session: AsyncSession) -> None:
    await run_freshness_agent(session)
    await run_freshness_agent(session)
    alerts = list((await session.scalars(select(Alert).where(Alert.severity == "warning"))).all())
    assert any(alert.title == "Freshness: customers" for alert in alerts)


@pytest.mark.asyncio
async def test_docs_agent_uses_heuristic_when_no_llm(session: AsyncSession) -> None:
    run = await run_docs_agent(session)
    tables = {t.name: t for t in (await session.scalars(select(TableAsset))).all()}
    assert run.status == "completed"
    orders = tables["orders"]
    descriptions = {col["name"]: col["description"] for col in orders.columns}
    assert descriptions["order_id"]
    assert "documented" in orders.tags
