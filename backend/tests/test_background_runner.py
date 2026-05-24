from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.domain import (
    Agent,
    AgentMcpGrant,
    AgentRun,
    AgentToolCall,
    Alert,
    Connector,
    MonitoringConfig,
    Workspace,
)
from app.services.agents.background_runner import (
    SYSTEM_HANDLERS,
    _failure_items,
    _run_generic_orchestration_failure_agent,
    due_background_agents,
    reclaim_expired_agent_runs,
    run_custom_background_agent,
    run_due_background_agents,
)
from app.services.agents.monitoring_common import enabled_monitoring_configs


@pytest.fixture
async def runner_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'runner.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_due_background_agents_respects_cadence(runner_session) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="freshness",
        display_name="Freshness",
        system_prompt="",
        kind="background",
        enabled=True,
        cadence_minutes=10,
    )
    runner_session.add(agent)
    await runner_session.flush()
    now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)

    assert [item.name for item in await due_background_agents(runner_session, now=now)] == ["freshness"]

    runner_session.add(
        AgentRun(
            workspace_id=workspace.id,
            agent_name="Freshness",
            status="completed",
            summary="done",
            timeline=[],
            created_at=now - timedelta(minutes=5),
        )
    )
    await runner_session.commit()

    assert await due_background_agents(runner_session, now=now) == []
    assert [item.name for item in await due_background_agents(runner_session, now=now + timedelta(minutes=5))] == [
        "freshness"
    ]


@pytest.mark.asyncio
async def test_due_background_agents_uses_legacy_system_run_names(runner_session) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="alerting",
        display_name="Alerting",
        system_prompt="",
        kind="background",
        enabled=True,
        cadence_minutes=5,
    )
    runner_session.add(agent)
    now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    runner_session.add(
        AgentRun(
            workspace_id=workspace.id,
            agent_name="Airflow Failure Agent",
            status="completed",
            summary="done",
            timeline=[],
            created_at=now - timedelta(minutes=4),
        )
    )
    await runner_session.commit()

    assert await due_background_agents(runner_session, now=now) == []
    assert [item.name for item in await due_background_agents(runner_session, now=now + timedelta(minutes=1))] == [
        "alerting"
    ]


@pytest.mark.asyncio
async def test_due_background_agents_skips_active_lease(runner_session) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="freshness",
        display_name="Freshness",
        system_prompt="",
        kind="background",
        enabled=True,
        cadence_minutes=5,
    )
    now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    runner_session.add_all(
        [
            agent,
            AgentRun(
                workspace_id=workspace.id,
                agent_name="Freshness",
                status="running",
                state="running",
                summary="running",
                timeline=[],
                started_at=now - timedelta(seconds=30),
                lease_token="lease-1",
                lease_expires_at=now + timedelta(seconds=30),
            ),
        ]
    )
    await runner_session.commit()

    assert await due_background_agents(runner_session, now=now) == []

    agent.force_run_requested_at = now
    await runner_session.commit()
    assert await due_background_agents(runner_session, now=now) == []


@pytest.mark.asyncio
async def test_reclaim_expired_agent_runs_marks_lease_failed(runner_session) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Freshness",
        status="running",
        state="running",
        summary="running",
        timeline=[],
        started_at=now - timedelta(minutes=3),
        lease_token="lease-1",
        lease_expires_at=now - timedelta(seconds=1),
    )
    runner_session.add(run)
    await runner_session.commit()

    reclaimed = await reclaim_expired_agent_runs(runner_session, now=now)
    await runner_session.refresh(run)

    assert reclaimed == 1
    assert run.state == "failed"
    assert run.status == "failed"
    assert run.error_message == "Lease expired before the background run completed."
    assert run.duration_ms and run.duration_ms >= 180000


@pytest.mark.asyncio
async def test_reclaim_expired_agent_runs_does_not_commit_caller_state(runner_session) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Freshness",
        status="running",
        state="running",
        summary="running",
        timeline=[],
        started_at=now - timedelta(minutes=3),
        lease_token="lease-1",
        lease_expires_at=now - timedelta(seconds=1),
    )
    runner_session.add(run)
    await runner_session.commit()
    run_id = run.id

    unsaved_agent = Agent(
        workspace_id=workspace.id,
        name="unsaved",
        display_name="Unsaved",
        system_prompt="",
        kind="background",
        enabled=True,
    )
    runner_session.add(unsaved_agent)

    reclaimed = await reclaim_expired_agent_runs(runner_session, now=now)
    await runner_session.rollback()

    assert reclaimed == 1
    assert await runner_session.scalar(select(Agent).where(Agent.name == "unsaved")) is None
    refreshed_run = await runner_session.get(AgentRun, run_id)
    assert refreshed_run is not None
    assert refreshed_run.state == "failed"


@pytest.mark.asyncio
async def test_custom_background_agent_uses_granted_mcp_sql(runner_session, tmp_path, monkeypatch) -> None:
    tool_db = tmp_path / "tool.sqlite"
    tool_engine = create_async_engine(f"sqlite+aiosqlite:///{tool_db}")
    async with tool_engine.begin() as conn:
        await conn.exec_driver_sql("create table refunds (id integer primary key)")
        await conn.exec_driver_sql("insert into refunds (id) values (1), (2)")
    await tool_engine.dispose()

    monkeypatch.setenv("DEMO_DATABASE_URL", f"sqlite+aiosqlite:///{tool_db}")
    from app.core.config import get_settings

    get_settings.cache_clear()

    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    connector = Connector(
        workspace_id=workspace.id,
        slug="sqlite",
        category="data_store",
        display_name="SQLite",
        status="real",
        credential_state="configured",
    )
    runner_session.add(connector)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="refund_monitor",
        display_name="Refund Monitor",
        system_prompt="",
        sql_query="select * from refunds",
        kind="background",
        enabled=True,
        cadence_minutes=5,
        thresholds={"rows_gt": 1},
        target_connector_id=connector.id,
    )
    runner_session.add(agent)
    await runner_session.flush()
    runner_session.add(
        AgentMcpGrant(agent_id=agent.id, connector_slug="sqlite", read_enabled=True, write_enabled=False)
    )
    await runner_session.commit()

    queue_run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Refund Monitor",
        status="running",
        state="running",
        summary="queued",
        timeline=[],
    )
    runner_session.add(queue_run)
    await runner_session.commit()

    run = await run_custom_background_agent(runner_session, agent, run_id=queue_run.id)
    alert = await runner_session.scalar(select(Alert).where(Alert.workspace_id == workspace.id))
    tool_call = await runner_session.scalar(select(AgentToolCall).where(AgentToolCall.run_id == queue_run.id))

    assert run.status == "completed"
    assert tool_call is not None
    assert tool_call.tool_name == "read_query_select"
    assert "alert created" in run.summary
    assert alert is not None
    assert alert.fingerprint and alert.fingerprint.startswith(f"custom:{agent.id}:")

    second_run = await run_custom_background_agent(runner_session, agent)
    alerts = (await runner_session.scalars(select(Alert).where(Alert.workspace_id == workspace.id))).all()
    assert "alert not created" in second_run.summary
    assert len(alerts) == 1

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_custom_background_agent_without_read_grant_skips_polling(runner_session, monkeypatch) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    connector = Connector(
        workspace_id=workspace.id,
        slug="sqlite",
        category="data_store",
        display_name="SQLite",
        status="real",
        credential_state="configured",
    )
    runner_session.add(connector)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="refund_monitor",
        display_name="Refund Monitor",
        system_prompt="",
        sql_query="select * from refunds",
        kind="background",
        enabled=True,
        cadence_minutes=5,
        thresholds={"rows_gt": 0},
        target_connector_id=connector.id,
    )
    runner_session.add(agent)
    await runner_session.flush()
    runner_session.add(
        AgentMcpGrant(agent_id=agent.id, connector_slug="sqlite", read_enabled=False, write_enabled=False)
    )
    await runner_session.commit()

    async def fail_if_polled(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("custom agent polled without a read grant")

    monkeypatch.setattr("app.services.agents.background_runner.execute_mcp_tool", fail_if_polled)

    run = await run_custom_background_agent(runner_session, agent)

    assert run.status == "skipped"
    assert "no read grant" in run.summary
    alerts = (await runner_session.scalars(select(Alert).where(Alert.workspace_id == workspace.id))).all()
    assert alerts == []


@pytest.mark.asyncio
async def test_custom_background_agent_honors_run_budget_before_tool_call(runner_session, monkeypatch) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    connector = Connector(
        workspace_id=workspace.id,
        slug="sqlite",
        category="data_store",
        display_name="SQLite",
        status="real",
        credential_state="configured",
    )
    runner_session.add(connector)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="refund_monitor",
        display_name="Refund Monitor",
        system_prompt="",
        sql_query="select * from refunds",
        kind="background",
        enabled=True,
        cadence_minutes=5,
        target_connector_id=connector.id,
    )
    runner_session.add(agent)
    await runner_session.flush()
    runner_session.add(AgentMcpGrant(agent_id=agent.id, connector_slug="sqlite", read_enabled=True))
    run = AgentRun(
        workspace_id=workspace.id,
        agent_name="Refund Monitor",
        status="running",
        state="running",
        summary="queued",
        timeline=[],
        started_at=datetime.now(UTC) - timedelta(seconds=2),
        budget_seconds=0,
        budget_tokens=100,
    )
    runner_session.add(run)
    await runner_session.commit()

    async def fail_if_polled(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("custom agent polled after budget was exceeded")

    monkeypatch.setattr("app.services.agents.background_runner.execute_mcp_tool", fail_if_polled)

    with pytest.raises(RuntimeError, match="Run time budget exceeded"):
        await run_custom_background_agent(runner_session, agent, run_id=run.id)

    refreshed = await runner_session.get(AgentRun, run.id)
    assert refreshed is not None
    assert refreshed.state == "timed_out"


@pytest.mark.asyncio
async def test_unified_monitoring_grants_take_precedence_over_legacy_configs(runner_session) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    connector = Connector(
        workspace_id=workspace.id,
        slug="airflow",
        category="orchestration",
        display_name="Airflow",
        status="real",
        credential_state="configured",
    )
    runner_session.add(connector)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="alerting",
        display_name="Alerting",
        system_prompt="",
        kind="background",
        enabled=True,
        cadence_minutes=5,
    )
    runner_session.add(agent)
    await runner_session.flush()
    runner_session.add_all(
        [
            AgentMcpGrant(agent_id=agent.id, connector_slug="airflow", read_enabled=False, write_enabled=False),
            MonitoringConfig(
                workspace_id=workspace.id,
                agent_name="airflow_failure_agent",
                connector_id=connector.id,
                enabled=True,
                thresholds={},
                notification_channels={},
            ),
        ]
    )
    await runner_session.commit()

    assert await enabled_monitoring_configs(
        runner_session,
        workspace.id,
        "airflow_failure_agent",
        ["airflow"],
    ) == []

    grant = await runner_session.scalar(
        select(AgentMcpGrant).where(
            AgentMcpGrant.agent_id == agent.id,
            AgentMcpGrant.connector_slug == "airflow",
        )
    )
    assert grant is not None
    grant.read_enabled = True
    await runner_session.commit()

    pairs = await enabled_monitoring_configs(
        runner_session,
        workspace.id,
        "airflow_failure_agent",
        ["airflow"],
    )
    assert len(pairs) == 1
    assert pairs[0][0] is None
    assert pairs[0][1].id == connector.id


@pytest.mark.asyncio
async def test_data_quality_agent_uses_granted_data_store_connectors_only(runner_session) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    sqlite = Connector(
        workspace_id=workspace.id,
        slug="sqlite",
        category="data_store",
        display_name="SQLite",
        status="ok",
        credential_state="configured",
    )
    postgres = Connector(
        workspace_id=workspace.id,
        slug="postgres",
        category="data_store",
        display_name="Postgres",
        status="ok",
        credential_state="configured",
    )
    airflow = Connector(
        workspace_id=workspace.id,
        slug="airflow",
        category="etl_orchestration",
        display_name="Airflow",
        status="ok",
        credential_state="configured",
    )
    runner_session.add_all([sqlite, postgres, airflow])
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="data_quality",
        display_name="Data Quality",
        system_prompt="",
        kind="background",
        enabled=True,
        cadence_minutes=5,
    )
    runner_session.add(agent)
    await runner_session.flush()
    runner_session.add_all(
        [
            AgentMcpGrant(agent_id=agent.id, connector_slug="sqlite", read_enabled=True),
            AgentMcpGrant(agent_id=agent.id, connector_slug="postgres", read_enabled=True),
            AgentMcpGrant(agent_id=agent.id, connector_slug="airflow", read_enabled=True),
        ]
    )
    await runner_session.commit()

    pairs = await enabled_monitoring_configs(
        runner_session,
        workspace.id,
        "schema_drift_agent",
        ["sqlite", "postgres"],
    )

    assert {connector.slug for _, connector in pairs} == {"sqlite", "postgres"}


@pytest.mark.asyncio
async def test_generic_orchestration_failure_agent_scans_granted_connectors(runner_session, monkeypatch) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    connector = Connector(
        workspace_id=workspace.id,
        slug="prefect",
        category="etl_orchestration",
        display_name="Prefect",
        status="ok",
        credential_state="configured",
    )
    runner_session.add(connector)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="alerting",
        display_name="Alerting",
        system_prompt="",
        kind="background",
        enabled=True,
        cadence_minutes=5,
    )
    runner_session.add(agent)
    await runner_session.flush()
    runner_session.add(AgentMcpGrant(agent_id=agent.id, connector_slug="prefect", read_enabled=True))
    await runner_session.commit()

    class FakeAdapter:
        async def list_failed_runs(self, credentials, since=None):  # noqa: ANN001
            return [{"id": "flow-bad", "name": "failing_flow", "state": "failed"}]

    retrieval_calls: list[dict] = []

    class FakeBrainRetriever:
        def __init__(self, session):  # noqa: ANN001
            self.session = session

        async def retrieve(self, workspace_id, question, **kwargs):  # noqa: ANN001, ANN003
            retrieval_calls.append(
                {"workspace_id": workspace_id, "question": question, "kwargs": kwargs}
            )
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(
                        canonical_name="failing_flow",
                        connector_slug="prefect",
                        summary="Prefect failing_flow loads customer metrics.",
                    )
                ],
                chunks=[],
                trace={"candidate_node_ids": ["node-1"]},
            )

    monkeypatch.setattr("app.services.agents.background_runner.adapter_for", lambda slug: FakeAdapter())
    monkeypatch.setattr("app.services.agents.background_runner.BrainRetriever", FakeBrainRetriever)

    run = await _run_generic_orchestration_failure_agent(runner_session)
    alerts = list((await runner_session.scalars(select(Alert).where(Alert.workspace_id == workspace.id))).all())

    assert run.status == "completed"
    assert "Scanned 1 orchestration connectors" in run.summary
    assert retrieval_calls == [
        {
            "workspace_id": workspace.id,
            "question": "Assess orchestration failure from prefect: flow-bad failing_flow failed",
            "kwargs": {"connector_slugs": ["prefect"], "top_k_nodes": 5, "chunks_per_node": 1},
        }
    ]
    assert len(alerts) == 1
    assert alerts[0].title == "flow-bad failed in Prefect"
    assert "Prefect failing_flow loads customer metrics." in alerts[0].detail


def test_failure_items_does_not_duplicate_nested_failures_under_failed_parent() -> None:
    failures = _failure_items({"status": "failed", "runs": [{"id": "nested", "status": "failed"}]})

    assert failures == [{"status": "failed", "runs": [{"id": "nested", "status": "failed"}]}]


@pytest.mark.asyncio
async def test_force_run_request_cleared_when_background_agent_fails(runner_session, monkeypatch) -> None:
    workspace = Workspace(name="Test")
    runner_session.add(workspace)
    await runner_session.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="freshness",
        display_name="Freshness",
        system_prompt="",
        kind="background",
        enabled=True,
        cadence_minutes=5,
        force_run_requested_at=datetime.now(UTC),
    )
    runner_session.add(agent)
    await runner_session.commit()

    async def fail_handler(session):  # noqa: ANN001
        raise RuntimeError("boom")

    async def fake_get_session():
        yield runner_session

    monkeypatch.setitem(SYSTEM_HANDLERS, "freshness", fail_handler)
    monkeypatch.setattr("app.services.agents.background_runner.get_session", fake_get_session)

    results = await run_due_background_agents(runner_session)

    refreshed = await runner_session.get(Agent, agent.id)
    assert refreshed is not None
    assert refreshed.force_run_requested_at is None
    assert len(results) == 1
    assert results[0].state == "failed"
