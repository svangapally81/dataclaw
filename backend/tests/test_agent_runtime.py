from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import AgentRun, Workspace
from app.services.agents.runtime import RunQueue


@pytest.fixture
async def runtime_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'runtime.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_queue_claim_start_complete(runtime_session) -> None:
    workspace = Workspace(name="Test")
    runtime_session.add(workspace)
    await runtime_session.flush()
    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Freshness",
        status="queued",
        state="queued",
        summary="queued",
        timeline=[],
    )
    runtime_session.add(run)
    await runtime_session.commit()

    queue = RunQueue(runtime_session)
    claimed = await queue.claim("worker-1", lease_seconds=30)
    assert claimed is not None
    assert claimed.id == run.id
    assert claimed.state == "leased"
    assert claimed.lease_token and claimed.lease_token.startswith("worker-1:")
    assert await queue.claim("worker-1", lease_seconds=30) is None

    running = await queue.start(run.id)
    assert running.state == "running"

    completed = await queue.complete(run.id, "done")
    assert completed.state == "completed"
    assert completed.status == "completed"
    assert completed.summary == "done"
    assert completed.lease_token is None
    assert completed.finished_at is not None


@pytest.mark.asyncio
async def test_run_queue_reclaims_expired_leases_until_retry_cap(runtime_session) -> None:
    workspace = Workspace(name="Test")
    runtime_session.add(workspace)
    await runtime_session.flush()
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Freshness",
        status="leased",
        state="leased",
        summary="leased",
        timeline=[],
        retry_count=2,
        lease_token="worker-1:abc",
        lease_expires_at=now - timedelta(seconds=1),
    )
    runtime_session.add(run)
    await runtime_session.commit()

    queue = RunQueue(runtime_session)
    assert await queue.reclaim_stale_leases(now=now, max_retries=3) == 1
    assert run.state == "queued"
    assert run.retry_count == 3
    assert run.lease_token is None

    run.state = "leased"
    run.status = "leased"
    run.lease_token = "worker-1:def"
    run.lease_expires_at = now - timedelta(seconds=1)
    await runtime_session.commit()

    assert await queue.reclaim_stale_leases(now=now, max_retries=3) == 1
    assert run.state == "failed"
    assert run.retry_count == 4
    assert run.error_message == "Run exceeded maximum lease retries."
