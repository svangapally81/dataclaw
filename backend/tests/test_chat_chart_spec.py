from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import Dataset, TableAsset, Workspace
from app.services.agents.chat import answer_question


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'chart.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        workspace = Workspace(name="Chart Test")
        session.add(workspace)
        await session.flush()
        dataset = Dataset(workspace_id=workspace.id, name="demo", source_type="sqlite", schema_name="main")
        session.add(dataset)
        await session.flush()
        session.add(
            TableAsset(
                dataset_id=dataset.id,
                name="orders",
                columns=[{"name": "month", "type": "text"}, {"name": "revenue", "type": "real"}],
                row_count=3,
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_chart_question_returns_vega_lite_spec(monkeypatch, session: AsyncSession) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = await answer_question(session, "show me revenue by month as a chart")
    assert response["chart_spec"]["$schema"].endswith("/vega-lite/v5.json")
    assert response["chart_spec"]["data"]["values"]


@pytest.mark.asyncio
async def test_chart_semantic_hint_returns_vega_lite_spec(monkeypatch, session: AsyncSession) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = await answer_question(session, "show me the revenue trend over time")
    assert response["chart_spec"]["$schema"].endswith("/vega-lite/v5.json")
    assert response["chart_spec"]["data"]["values"]
