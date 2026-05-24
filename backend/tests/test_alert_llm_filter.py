import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import Agent, Workspace
from app.services.agents.alert_llm_filter import should_alert


@pytest.fixture
async def filter_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'filter.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_should_alert_keeps_when_filter_disabled(filter_session) -> None:
    workspace = Workspace(name="Test")
    filter_session.add(workspace)
    await filter_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="alerting",
        display_name="Alerting",
        system_prompt="",
        kind="background",
        uses_llm_filter=False,
    )

    assert await should_alert(filter_session, agent, {"severity": "warning"}) == (True, "LLM filter disabled.")
